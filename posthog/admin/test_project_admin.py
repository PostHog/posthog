from datetime import timedelta

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import Group
from django.contrib.messages.storage.fallback import FallbackStorage
from django.core.exceptions import PermissionDenied
from django.test import RequestFactory, override_settings
from django.utils import timezone

from temporalio.common import WorkflowIDConflictPolicy

from posthog.admin.admins.project_admin import ProjectAdmin
from posthog.admin.authorization import DELETION_AUTHORIZED_GROUP
from posthog.models import Project


def _attach_messages(request) -> None:
    request.session = {}
    request._messages = FallbackStorage(request)


def _fake_reverse(name, args=None, kwargs=None):
    if args:
        return f"/{name}/{'/'.join(str(a) for a in args)}/"
    return f"/{name}/"


@time_machine.travel("2024-01-01 12:00:00", tick=False)
class TestProjectAdminDeleteNow(BaseTest):
    def setUp(self):
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.user.groups.add(Group.objects.get_or_create(name=DELETION_AUTHORIZED_GROUP)[0])
        self.factory = RequestFactory()
        self.admin = ProjectAdmin(Project, AdminSite())
        self._mark_pending(hours=48)

    def _mark_pending(self, hours: float) -> None:
        Project.objects.filter(id=self.project.id).update(
            is_pending_deletion=True, deletion_scheduled_at=timezone.now() + timedelta(hours=hours)
        )

    def _call(self, method: str = "POST", start_side_effect=None):
        path = f"/admin/posthog/project/{self.project.pk}/delete-now/"
        http_request = self.factory.post(path) if method == "POST" else self.factory.get(path)
        http_request.user = self.user
        _attach_messages(http_request)
        with (
            patch("posthog.admin.admins.project_admin.reverse", side_effect=_fake_reverse),
            patch(
                "posthog.temporal.delete_teams.dispatch.start_delete_project_data_workflow",
                side_effect=start_side_effect,
            ) as mock_start,
        ):
            response = self.admin.delete_now_view(http_request, str(self.project.pk))
        return response, mock_start

    def test_post_deletes_pending_project_now(self):
        response, mock_start = self._call()

        self.assertEqual(response.status_code, 302)
        self.project.refresh_from_db()
        self.assertTrue(self.project.is_pending_deletion)
        self.assertEqual(self.project.deletion_scheduled_at, timezone.now())
        mock_start.assert_called_once()
        self.assertIsNone(mock_start.call_args.kwargs["start_delay"])
        self.assertEqual(mock_start.call_args.kwargs["id_conflict_policy"], WorkflowIDConflictPolicy.TERMINATE_EXISTING)

    def test_post_rejected_when_deletion_already_started(self):
        self._mark_pending(hours=-1)

        response, mock_start = self._call()

        self.assertEqual(response.status_code, 302)
        self.project.refresh_from_db()
        self.assertTrue(self.project.is_pending_deletion)
        self.assertEqual(self.project.deletion_scheduled_at, timezone.now() - timedelta(hours=1))
        mock_start.assert_not_called()

    def test_failed_immediate_start_keeps_original_schedule(self):
        self._mark_pending(hours=2)

        response, mock_start = self._call(start_side_effect=Exception("temporal unavailable"))

        self.assertEqual(response.status_code, 302)
        mock_start.assert_called_once()
        self.project.refresh_from_db()
        self.assertTrue(self.project.is_pending_deletion)
        self.assertEqual(self.project.deletion_scheduled_at, timezone.now() + timedelta(hours=2))

    def test_get_redirects_without_deleting(self):
        response, mock_start = self._call(method="GET")

        self.assertEqual(response.status_code, 302)
        mock_start.assert_not_called()
        self.project.refresh_from_db()
        self.assertEqual(self.project.deletion_scheduled_at, timezone.now() + timedelta(hours=48))

    @override_settings(DISABLE_BULK_DELETES=True)
    def test_bulk_delete_guard_keeps_original_schedule(self):
        self._mark_pending(hours=2)

        response, mock_start = self._call()

        self.assertEqual(response.status_code, 302)
        mock_start.assert_not_called()
        self.project.refresh_from_db()
        self.assertTrue(self.project.is_pending_deletion)
        self.assertEqual(self.project.deletion_scheduled_at, timezone.now() + timedelta(hours=2))

    def test_staff_outside_deletion_group_cannot_delete_now(self):
        self.user.groups.clear()

        with self.assertRaises(PermissionDenied):
            self._call()

        self.project.refresh_from_db()
        self.assertTrue(self.project.is_pending_deletion)
        self.assertEqual(self.project.deletion_scheduled_at, timezone.now() + timedelta(hours=48))
