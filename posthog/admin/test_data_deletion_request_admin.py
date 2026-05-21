from datetime import datetime, timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import Group
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory, override_settings

from parameterized import parameterized

from posthog.admin.admins.data_deletion_request_admin import DataDeletionRequestAdmin
from posthog.models.data_deletion_request import DataDeletionRequest, ExecutionMode, RequestStatus, RequestType


def _attach_messages(request) -> None:
    request.session = {}
    request._messages = FallbackStorage(request)


def _fake_reverse(name, args=None, kwargs=None):
    if args:
        return f"/{name}/{'/'.join(str(a) for a in args)}/"
    return f"/{name}/"


@override_settings(STORAGES={"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class TestDataDeletionRequestAdminApprovalFlow(BaseTest):
    def setUp(self):
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        clickhouse_team, _ = Group.objects.get_or_create(name="ClickHouse Team")
        self.user.groups.add(clickhouse_team)

        self.factory = RequestFactory()
        self.admin = DataDeletionRequestAdmin(DataDeletionRequest, AdminSite())

    def _pending_request(self, request_type: str = RequestType.EVENT_REMOVAL, properties: list | None = None):
        return DataDeletionRequest.objects.create(
            team_id=self.team.id,
            request_type=request_type,
            events=["$pageview"],
            properties=properties or [],
            start_time=datetime.now() - timedelta(days=7),
            end_time=datetime.now(),
            status=RequestStatus.PENDING,
        )

    def _call_approve(self, method: str, request: DataDeletionRequest, data: dict | None = None, user=None):
        path = f"/admin/posthog/datadeletionrequest/{request.pk}/approve/"
        if method == "GET":
            http_request = self.factory.get(path)
        else:
            http_request = self.factory.post(path, data or {})
        http_request.user = user or self.user
        _attach_messages(http_request)
        with patch("posthog.admin.admins.data_deletion_request_admin.reverse", side_effect=_fake_reverse):
            return self.admin.approve_view(http_request, str(request.pk))

    def test_approve_view_get_renders_picker_for_event_removal(self):
        request = self._pending_request()
        response = self._call_approve("GET", request)

        self.assertEqual(response.status_code, 200)
        context = response.context_data
        self.assertTrue(context["supports_deferred"])
        self.assertEqual(context["default_execution_mode"], ExecutionMode.IMMEDIATE)

    def test_approve_view_get_hides_picker_for_property_removal(self):
        request = self._pending_request(request_type=RequestType.PROPERTY_REMOVAL, properties=["$ip"])
        response = self._call_approve("GET", request)

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context_data["supports_deferred"])

    @parameterized.expand(
        [
            ("deferred", ExecutionMode.DEFERRED),
            ("immediate", ExecutionMode.IMMEDIATE),
        ]
    )
    def test_approve_view_post_persists_execution_mode_for_event_removal(self, _name, execution_mode):
        request = self._pending_request()
        response = self._call_approve("POST", request, {"execution_mode": execution_mode.value})

        self.assertEqual(response.status_code, 302)
        request.refresh_from_db()
        self.assertEqual(request.status, RequestStatus.APPROVED)
        self.assertEqual(request.execution_mode, execution_mode)
        self.assertTrue(request.approved)

    def test_approve_view_post_deferred_rejected_for_property_removal(self):
        request = self._pending_request(request_type=RequestType.PROPERTY_REMOVAL, properties=["$ip"])
        response = self._call_approve("POST", request, {"execution_mode": ExecutionMode.DEFERRED.value})

        self.assertEqual(response.status_code, 302)
        request.refresh_from_db()
        self.assertEqual(request.status, RequestStatus.PENDING)

    def test_approve_view_rejects_non_clickhouse_team_user(self):
        request = self._pending_request()
        self.user.groups.clear()
        response = self._call_approve("POST", request, {"execution_mode": ExecutionMode.IMMEDIATE.value})

        self.assertEqual(response.status_code, 302)
        request.refresh_from_db()
        self.assertEqual(request.status, RequestStatus.PENDING)

    def test_approve_view_rejects_invalid_execution_mode(self):
        request = self._pending_request()
        response = self._call_approve("POST", request, {"execution_mode": "bogus"})

        self.assertEqual(response.status_code, 302)
        request.refresh_from_db()
        self.assertEqual(request.status, RequestStatus.PENDING)


@override_settings(STORAGES={"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class TestDataDeletionRequestAdminRetry(BaseTest):
    def setUp(self):
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        clickhouse_team, _ = Group.objects.get_or_create(name="ClickHouse Team")
        self.user.groups.add(clickhouse_team)

        self.factory = RequestFactory()
        self.admin = DataDeletionRequestAdmin(DataDeletionRequest, AdminSite())

    def _failed_request(self, attempt_count: int = 1):
        approved_at = datetime.now() - timedelta(hours=2)
        return DataDeletionRequest.objects.create(
            team_id=self.team.id,
            request_type=RequestType.EVENT_REMOVAL,
            events=["$pageview"],
            start_time=datetime.now() - timedelta(days=7),
            end_time=datetime.now(),
            status=RequestStatus.FAILED,
            approved=True,
            approved_by=self.user,
            approved_at=approved_at,
            execution_mode=ExecutionMode.IMMEDIATE,
            attempt_count=attempt_count,
            first_executed_at=approved_at,
            last_executed_at=approved_at,
        )

    def _call_retry(self, method: str, request: DataDeletionRequest, user=None):
        path = f"/admin/posthog/datadeletionrequest/{request.pk}/retry/"
        if method == "GET":
            http_request = self.factory.get(path)
        else:
            http_request = self.factory.post(path, {})
        http_request.user = user or self.user
        _attach_messages(http_request)
        with patch("posthog.admin.admins.data_deletion_request_admin.reverse", side_effect=_fake_reverse):
            return self.admin.retry_view(http_request, str(request.pk))

    def test_retry_view_post_re_promotes_failed_to_approved(self):
        request = self._failed_request(attempt_count=2)
        request.refresh_from_db()
        original_approved_at = request.approved_at

        response = self._call_retry("POST", request)

        self.assertEqual(response.status_code, 302)
        request.refresh_from_db()
        self.assertEqual(request.status, RequestStatus.APPROVED)
        self.assertEqual(request.approved_by, self.user)
        self.assertEqual(request.approved_at, original_approved_at)
        self.assertTrue(request.approved)
        self.assertEqual(request.attempt_count, 2)

    def test_retry_view_get_does_not_change_status(self):
        request = self._failed_request()
        response = self._call_retry("GET", request)

        self.assertEqual(response.status_code, 302)
        request.refresh_from_db()
        self.assertEqual(request.status, RequestStatus.FAILED)

    def test_retry_view_rejects_non_clickhouse_team_user(self):
        request = self._failed_request()
        self.user.groups.clear()
        response = self._call_retry("POST", request)

        self.assertEqual(response.status_code, 302)
        request.refresh_from_db()
        self.assertEqual(request.status, RequestStatus.FAILED)

    @parameterized.expand(
        [
            ("draft", RequestStatus.DRAFT),
            ("pending", RequestStatus.PENDING),
            ("approved", RequestStatus.APPROVED),
            ("in_progress", RequestStatus.IN_PROGRESS),
            ("queued", RequestStatus.QUEUED),
            ("completed", RequestStatus.COMPLETED),
        ]
    )
    def test_retry_view_rejects_non_failed_status(self, _name, status):
        request = self._failed_request()
        DataDeletionRequest.objects.filter(pk=request.pk).update(status=status)

        response = self._call_retry("POST", request)

        self.assertEqual(response.status_code, 302)
        request.refresh_from_db()
        self.assertEqual(request.status, status)


@override_settings(STORAGES={"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class TestDataDeletionRequestAdminChangeView(BaseTest):
    def setUp(self):
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.factory = RequestFactory()
        self.admin = DataDeletionRequestAdmin(DataDeletionRequest, AdminSite())

    def _make_request(self, status: str):
        return DataDeletionRequest.objects.create(
            team_id=self.team.id,
            request_type=RequestType.EVENT_REMOVAL,
            events=["$pageview"],
            start_time=datetime.now() - timedelta(days=7),
            end_time=datetime.now(),
            status=status,
        )

    def _can_retry(self, request: DataDeletionRequest, in_clickhouse_team: bool) -> bool:
        if in_clickhouse_team:
            clickhouse_team, _ = Group.objects.get_or_create(name="ClickHouse Team")
            self.user.groups.add(clickhouse_team)
        else:
            self.user.groups.clear()

        path = f"/admin/posthog/datadeletionrequest/{request.pk}/change/"
        http_request = self.factory.get(path)
        http_request.user = self.user
        _attach_messages(http_request)
        captured: dict = {}

        def _capture_super(self_admin, http_req, object_id, form_url, extra_context):
            captured.update(extra_context)
            from django.http import HttpResponse

            return HttpResponse(status=200)

        with (
            patch("posthog.admin.admins.data_deletion_request_admin.reverse", side_effect=_fake_reverse),
            patch("django.contrib.admin.ModelAdmin.change_view", _capture_super),
        ):
            self.admin.change_view(http_request, str(request.pk))
        return captured.get("can_retry", False)

    def test_can_retry_only_when_failed_and_clickhouse_team(self):
        failed = self._make_request(RequestStatus.FAILED)
        self.assertTrue(self._can_retry(failed, in_clickhouse_team=True))

    def test_can_retry_false_when_not_in_clickhouse_team(self):
        failed = self._make_request(RequestStatus.FAILED)
        self.assertFalse(self._can_retry(failed, in_clickhouse_team=False))

    @parameterized.expand(
        [
            ("draft", RequestStatus.DRAFT),
            ("pending", RequestStatus.PENDING),
            ("approved", RequestStatus.APPROVED),
            ("in_progress", RequestStatus.IN_PROGRESS),
            ("queued", RequestStatus.QUEUED),
            ("completed", RequestStatus.COMPLETED),
        ]
    )
    def test_can_retry_false_for_non_failed_status(self, _name, status):
        request = self._make_request(status)
        self.assertFalse(self._can_retry(request, in_clickhouse_team=True))
