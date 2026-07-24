from freezegun import freeze_time
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory
from django.urls import reverse

from posthog.admin.admins.organization_admin import OrganizationAdmin
from posthog.models import Organization


def _attach_messages(request) -> None:
    request.session = {}
    request._messages = FallbackStorage(request)


def _fake_reverse(name, args=None, kwargs=None):
    return f"/{name}/"


class TestSendAIObservabilityUsageReportAdmin(BaseTest):
    def setUp(self):
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.factory = RequestFactory()
        self.admin = OrganizationAdmin(Organization, AdminSite())
        reverse(
            "admin:index"
        )  # warm posthog.urls import outside freeze_time: the first reverse() lazily imports pydantic v1, which breaks under a frozen datetime.date

    def _post(self, report_date: str):
        http_request = self.factory.post(
            "/admin/posthog/organization/send-ai-observability-usage-report/", {"report_date": report_date}
        )
        http_request.user = self.user
        _attach_messages(http_request)
        with (
            patch("posthog.admin.admins.organization_admin.reverse", side_effect=_fake_reverse),
            patch("posthog.admin.admins.organization_admin.call_command") as mock_call_command,
        ):
            response = self.admin.send_ai_observability_usage_report_view(http_request)
        return response, mock_call_command

    @freeze_time("2026-07-22T12:00:00Z")
    def test_valid_post_dispatches_async_command_for_date(self):
        response, mock_call_command = self._post("2026-07-15")

        self.assertEqual(response.status_code, 302)
        mock_call_command.assert_called_once_with("send_ai_observability_usage_report", "--date=2026-07-15", "--async")

    @freeze_time("2026-07-22T12:00:00Z")
    def test_far_future_date_is_rejected_and_not_dispatched(self):
        response, mock_call_command = self._post("2026-07-30")

        self.assertEqual(response.status_code, 200)
        mock_call_command.assert_not_called()

    def test_get_renders_form_without_dispatching(self):
        http_request = self.factory.get("/admin/posthog/organization/send-ai-observability-usage-report/")
        http_request.user = self.user
        _attach_messages(http_request)
        with (
            patch("posthog.admin.admins.organization_admin.reverse", side_effect=_fake_reverse),
            patch("posthog.admin.admins.organization_admin.call_command") as mock_call_command,
        ):
            response = self.admin.send_ai_observability_usage_report_view(http_request)

        self.assertEqual(response.status_code, 200)
        mock_call_command.assert_not_called()
