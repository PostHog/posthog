from posthog.test.base import BaseTest

from django.core.management import call_command
from django.core.management.base import CommandError

from parameterized import parameterized

from posthog.models import Organization


class TestRepairOrganizationSlug(BaseTest):
    def _create_organization_with_stale_slug(self) -> Organization:
        organization = Organization.objects.create(name="Old Inc")
        Organization.objects.filter(pk=organization.pk).update(name="New Inc")
        organization.refresh_from_db()
        return organization

    @parameterized.expand([("by_id",), ("by_slug",)])
    def test_live_run_repairs_the_slug(self, lookup):
        organization = self._create_organization_with_stale_slug()
        identifier = str(organization.id) if lookup == "by_id" else organization.slug

        call_command("repair_organization_slug", identifier, "--live-run")

        organization.refresh_from_db()
        self.assertEqual(organization.slug, "new-inc")

    def test_dry_run_leaves_the_slug_alone(self):
        organization = self._create_organization_with_stale_slug()

        call_command("repair_organization_slug", str(organization.id))

        organization.refresh_from_db()
        self.assertEqual(organization.slug, "old-inc")

    def test_unknown_organization_fails(self):
        with self.assertRaises(CommandError):
            call_command("repair_organization_slug", "no-such-org", "--live-run")
