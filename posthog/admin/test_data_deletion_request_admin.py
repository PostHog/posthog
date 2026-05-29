from datetime import datetime, timedelta

from freezegun import freeze_time
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


@override_settings(STORAGES={"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class TestDataDeletionRequestAdminSubmitView(BaseTest):
    def setUp(self):
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.factory = RequestFactory()
        self.admin = DataDeletionRequestAdmin(DataDeletionRequest, AdminSite())

    def _property_removal_request(self, properties=None, person_properties=None):
        return DataDeletionRequest.objects.create(
            team_id=self.team.id,
            request_type=RequestType.PROPERTY_REMOVAL,
            events=["$pageview"],
            properties=properties or [],
            person_properties=person_properties or [],
            start_time=datetime.now() - timedelta(days=7),
            end_time=datetime.now(),
            status=RequestStatus.DRAFT,
        )

    def _call_submit(self, request: DataDeletionRequest, method: str = "POST"):
        path = f"/admin/posthog/datadeletionrequest/{request.pk}/submit/"
        http_request = self.factory.post(path) if method == "POST" else self.factory.get(path)
        http_request.user = self.user
        _attach_messages(http_request)
        with patch("posthog.admin.admins.data_deletion_request_admin.reverse", side_effect=_fake_reverse):
            return self.admin.submit_view(http_request, str(request.pk))

    def test_submit_with_properties_only_succeeds(self):
        request = self._property_removal_request(properties=["$ip"])
        response = self._call_submit(request)
        self.assertEqual(response.status_code, 302)
        request.refresh_from_db()
        self.assertEqual(request.status, RequestStatus.PENDING)

    def test_submit_with_person_properties_only_succeeds(self):
        request = self._property_removal_request(person_properties=["email"])
        response = self._call_submit(request)
        self.assertEqual(response.status_code, 302)
        request.refresh_from_db()
        self.assertEqual(request.status, RequestStatus.PENDING)

    def test_submit_with_both_properties_succeeds(self):
        request = self._property_removal_request(properties=["$ip"], person_properties=["email"])
        response = self._call_submit(request)
        self.assertEqual(response.status_code, 302)
        request.refresh_from_db()
        self.assertEqual(request.status, RequestStatus.PENDING)

    def test_submit_with_both_empty_is_rejected(self):
        request = self._property_removal_request(properties=[], person_properties=[])
        response = self._call_submit(request)
        self.assertEqual(response.status_code, 302)
        request.refresh_from_db()
        self.assertEqual(request.status, RequestStatus.DRAFT)

    def test_submit_get_exposes_can_submit_flag(self):
        ok = self._property_removal_request(properties=["$ip"])
        empty = self._property_removal_request(properties=[], person_properties=[])

        path_ok = f"/admin/posthog/datadeletionrequest/{ok.pk}/submit/"
        http_req_ok = self.factory.get(path_ok)
        http_req_ok.user = self.user
        _attach_messages(http_req_ok)

        path_empty = f"/admin/posthog/datadeletionrequest/{empty.pk}/submit/"
        http_req_empty = self.factory.get(path_empty)
        http_req_empty.user = self.user
        _attach_messages(http_req_empty)

        with patch("posthog.admin.admins.data_deletion_request_admin.reverse", side_effect=_fake_reverse):
            resp_ok = self.admin.submit_view(http_req_ok, str(ok.pk))
            resp_empty = self.admin.submit_view(http_req_empty, str(empty.pk))

        self.assertTrue(resp_ok.context_data["can_submit"])
        self.assertFalse(resp_empty.context_data["can_submit"])
        self.assertTrue(resp_empty.context_data["missing_properties"])


@freeze_time("2025-01-15 12:00:00")
@override_settings(STORAGES={"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}})
class TestDataDeletionRequestAdminSaveModel(BaseTest):
    def setUp(self):
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.factory = RequestFactory()
        self.admin = DataDeletionRequestAdmin(DataDeletionRequest, AdminSite())

    def _call_save(self, obj: DataDeletionRequest, changed_data: list[str] | None = None):
        path = f"/admin/posthog/datadeletionrequest/{obj.pk}/change/"
        http_request = self.factory.post(path)
        http_request.user = self.user
        _attach_messages(http_request)

        class _FakeForm:
            changed_data: list[str] = []

        form = _FakeForm()
        if changed_data is not None:
            form.changed_data = changed_data
        self.admin.save_model(http_request, obj, form, change=True)

    def test_event_removal_clears_properties_on_save(self):
        obj = DataDeletionRequest.objects.create(
            team_id=self.team.id,
            request_type=RequestType.EVENT_REMOVAL,
            events=["$pageview"],
            properties=["$ip"],
            start_time=datetime.now() - timedelta(days=7),
            end_time=datetime.now(),
            status=RequestStatus.DRAFT,
        )
        self._call_save(obj)
        obj.refresh_from_db()
        self.assertEqual(obj.properties, [])

    def test_event_removal_clears_person_properties_on_save(self):
        obj = DataDeletionRequest.objects.create(
            team_id=self.team.id,
            request_type=RequestType.EVENT_REMOVAL,
            events=["$pageview"],
            person_properties=["email"],
            start_time=datetime.now() - timedelta(days=7),
            end_time=datetime.now(),
            status=RequestStatus.DRAFT,
        )
        self._call_save(obj)
        obj.refresh_from_db()
        self.assertEqual(obj.person_properties, [])

    def test_event_removal_clears_both_on_save(self):
        obj = DataDeletionRequest.objects.create(
            team_id=self.team.id,
            request_type=RequestType.EVENT_REMOVAL,
            events=["$pageview"],
            properties=["$ip"],
            person_properties=["email"],
            start_time=datetime.now() - timedelta(days=7),
            end_time=datetime.now(),
            status=RequestStatus.DRAFT,
        )
        self._call_save(obj)
        obj.refresh_from_db()
        self.assertEqual(obj.properties, [])
        self.assertEqual(obj.person_properties, [])

    def test_property_removal_preserves_both_fields_on_save(self):
        obj = DataDeletionRequest.objects.create(
            team_id=self.team.id,
            request_type=RequestType.PROPERTY_REMOVAL,
            events=["$pageview"],
            properties=["$ip"],
            person_properties=["email"],
            start_time=datetime.now() - timedelta(days=7),
            end_time=datetime.now(),
            status=RequestStatus.DRAFT,
        )
        self._call_save(obj)
        obj.refresh_from_db()
        self.assertEqual(obj.properties, ["$ip"])
        self.assertEqual(obj.person_properties, ["email"])


@freeze_time("2025-01-15 12:00:00")
class TestDataDeletionRequestModelValidation(BaseTest):
    def test_person_removal_rejects_person_properties_field(self):
        from django.core.exceptions import ValidationError

        obj = DataDeletionRequest(
            team_id=self.team.id,
            request_type=RequestType.PERSON_REMOVAL,
            person_uuids=["00000000-0000-0000-0000-000000000001"],
            person_drop_profiles=True,
            person_properties=["email"],
        )
        with self.assertRaises(ValidationError) as cm:
            obj.clean()
        self.assertIn("person_properties", cm.exception.message_dict)

    def test_person_removal_without_person_properties_is_valid(self):
        from django.core.exceptions import ValidationError

        obj = DataDeletionRequest(
            team_id=self.team.id,
            request_type=RequestType.PERSON_REMOVAL,
            person_uuids=["00000000-0000-0000-0000-000000000001"],
            person_drop_profiles=True,
            person_properties=[],
        )
        try:
            obj.clean()
        except ValidationError as exc:
            if "person_properties" in (exc.message_dict if hasattr(exc, "message_dict") else {}):
                self.fail(f"clean() raised unexpected ValidationError for person_properties: {exc}")

    @parameterized.expand(
        [
            ("properties_only", ["$ip"], []),
            ("person_properties_only", [], ["email"]),
            ("both", ["$ip"], ["email"]),
        ]
    )
    def test_property_removal_does_not_validate_field_presence_at_model_level(
        self, _name, properties, person_properties
    ):
        obj = DataDeletionRequest(
            team_id=self.team.id,
            request_type=RequestType.PROPERTY_REMOVAL,
            events=["$pageview"],
            properties=properties,
            person_properties=person_properties,
            start_time=datetime.now() - timedelta(days=7),
            end_time=datetime.now(),
        )
        from django.core.exceptions import ValidationError

        try:
            obj.clean()
        except ValidationError as exc:
            msg_dict = exc.message_dict if hasattr(exc, "message_dict") else {}
            self.assertNotIn("properties", msg_dict)
            self.assertNotIn("person_properties", msg_dict)
