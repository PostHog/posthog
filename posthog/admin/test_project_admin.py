from django.contrib.admin.sites import AdminSite
from django.test import SimpleTestCase

from posthog.admin.admins.project_admin import ProjectAdmin
from posthog.models import Project


class TestProjectAdmin(SimpleTestCase):
    def test_deletion_state_fields_are_read_only(self):
        admin = ProjectAdmin(Project, AdminSite())

        self.assertIn("is_pending_deletion", admin.readonly_fields)
        self.assertIn("deletion_scheduled_at", admin.readonly_fields)
