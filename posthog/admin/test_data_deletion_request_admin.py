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
