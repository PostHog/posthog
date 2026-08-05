from posthog.test.base import BaseTest
from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import Group
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory, override_settings

from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.admin.admins.organization_admin import OrganizationAdmin
from posthog.admin.admins.project_admin import ProjectAdmin
from posthog.admin.authorization import DELETION_AUTHORIZED_GROUP
from posthog.models import Organization, Project


def _attach_messages(request) -> None:
    request.session = {}
    request._messages = FallbackStorage(request)


def _fake_reverse(name, args=None, kwargs=None):
    if args:
        return f"/{name}/{'/'.join(str(a) for a in args)}/"
    return f"/{name}/"


class TestOrganizationAdminTriggerDeletion(BaseTest):
    def setUp(self):
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.user.groups.add(Group.objects.get_or_create(name=DELETION_AUTHORIZED_GROUP)[0])
        self.factory = RequestFactory()
        self.admin = OrganizationAdmin(Organization, AdminSite())

    def _call(self, method: str, start_side_effect=None):
        path = f"/admin/posthog/organization/{self.organization.pk}/trigger-deletion/"
        http_request = self.factory.post(path) if method == "POST" else self.factory.get(path)
        http_request.user = self.user
        _attach_messages(http_request)
        with (
            patch("posthog.admin.admins.organization_admin.reverse", side_effect=_fake_reverse),
            patch(
                "posthog.temporal.delete_teams.dispatch.start_delete_organization_workflow",
                side_effect=start_side_effect,
            ) as mock_start,
        ):
            response = self.admin.trigger_deletion_view(http_request, str(self.organization.pk))
        return response, mock_start

    def test_post_starts_org_deletion_and_marks_pending(self):
        response, mock_start = self._call("POST")

        self.assertEqual(response.status_code, 302)
        mock_start.assert_called_once()
        kwargs = mock_start.call_args.kwargs
        self.assertEqual(kwargs["organization_id"], str(self.organization.pk))
        self.assertEqual(kwargs["team_ids"], [self.team.pk])
        self.assertEqual(kwargs["user_id"], self.user.pk)
        self.assertIn(self.team.name, kwargs["project_names"])
        self.organization.refresh_from_db()
        self.assertTrue(self.organization.is_pending_deletion)

    def test_get_does_not_start_workflow(self):
        response, mock_start = self._call("GET")

        self.assertEqual(response.status_code, 302)
        mock_start.assert_not_called()
        self.organization.refresh_from_db()
        self.assertFalse(self.organization.is_pending_deletion)

    @override_settings(DISABLE_BULK_DELETES=True)
    def test_disable_bulk_deletes_blocks_dispatch(self):
        response, mock_start = self._call("POST")

        self.assertEqual(response.status_code, 302)
        mock_start.assert_not_called()
        self.organization.refresh_from_db()
        self.assertFalse(self.organization.is_pending_deletion)

    def test_staff_outside_deletion_group_cannot_dispatch(self):
        self.user.groups.clear()

        response, mock_start = self._call("POST")

        self.assertEqual(response.status_code, 302)
        mock_start.assert_not_called()
        self.organization.refresh_from_db()
        self.assertFalse(self.organization.is_pending_deletion)

    def test_already_pending_deletion_is_rejected(self):
        self.organization.is_pending_deletion = True
        self.organization.save(update_fields=["is_pending_deletion"])

        response, mock_start = self._call("POST")

        self.assertEqual(response.status_code, 302)
        mock_start.assert_not_called()

    def test_dispatch_failure_rolls_back_pending(self):
        response, mock_start = self._call("POST", start_side_effect=Exception("boom"))

        self.assertEqual(response.status_code, 302)
        mock_start.assert_called_once()
        self.organization.refresh_from_db()
        self.assertFalse(self.organization.is_pending_deletion)

    def test_already_started_workflow_keeps_pending(self):
        response, mock_start = self._call("POST", start_side_effect=WorkflowAlreadyStartedError("id", "type"))

        self.assertEqual(response.status_code, 302)
        mock_start.assert_called_once()
        self.organization.refresh_from_db()
        self.assertTrue(self.organization.is_pending_deletion)


class TestProjectAdminTriggerDeletion(BaseTest):
    def setUp(self):
        super().setUp()
        self.user.is_staff = True
        self.user.save()
        self.user.groups.add(Group.objects.get_or_create(name=DELETION_AUTHORIZED_GROUP)[0])
        self.factory = RequestFactory()
        self.admin = ProjectAdmin(Project, AdminSite())

    def _call(self, method: str, start_side_effect=None):
        path = f"/admin/posthog/project/{self.project.pk}/trigger-deletion/"
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
            response = self.admin.trigger_deletion_view(http_request, str(self.project.pk))
        return response, mock_start

    def test_post_starts_project_deletion_and_marks_pending(self):
        response, mock_start = self._call("POST")

        self.assertEqual(response.status_code, 302)
        mock_start.assert_called_once()
        kwargs = mock_start.call_args.kwargs
        self.assertEqual(kwargs["project_id"], self.project.pk)
        self.assertEqual(kwargs["team_ids"], [self.team.pk])
        self.assertEqual(kwargs["user_id"], self.user.pk)
        self.assertEqual(kwargs["project_name"], self.project.name)
        self.project.refresh_from_db()
        self.assertTrue(self.project.is_pending_deletion)

    def test_get_does_not_start_workflow(self):
        response, mock_start = self._call("GET")

        self.assertEqual(response.status_code, 302)
        mock_start.assert_not_called()
        self.project.refresh_from_db()
        self.assertFalse(self.project.is_pending_deletion)

    @override_settings(DISABLE_BULK_DELETES=True)
    def test_disable_bulk_deletes_blocks_dispatch(self):
        response, mock_start = self._call("POST")

        self.assertEqual(response.status_code, 302)
        mock_start.assert_not_called()
        self.project.refresh_from_db()
        self.assertFalse(self.project.is_pending_deletion)

    def test_staff_outside_deletion_group_cannot_dispatch(self):
        self.user.groups.clear()

        response, mock_start = self._call("POST")

        self.assertEqual(response.status_code, 302)
        mock_start.assert_not_called()
        self.project.refresh_from_db()
        self.assertFalse(self.project.is_pending_deletion)

    def test_already_pending_deletion_is_rejected(self):
        self.project.is_pending_deletion = True
        self.project.save(update_fields=["is_pending_deletion"])

        response, mock_start = self._call("POST")

        self.assertEqual(response.status_code, 302)
        mock_start.assert_not_called()

    def test_dispatch_failure_rolls_back_pending(self):
        response, mock_start = self._call("POST", start_side_effect=Exception("boom"))

        self.assertEqual(response.status_code, 302)
        mock_start.assert_called_once()
        self.project.refresh_from_db()
        self.assertFalse(self.project.is_pending_deletion)
