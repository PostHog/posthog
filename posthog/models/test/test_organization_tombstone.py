import uuid

from posthog.test.base import BaseTest
from unittest.mock import patch

from rest_framework.exceptions import ValidationError

from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.organization_domain import OrganizationDomain
from posthog.models.organization_invite import OrganizationInvite
from posthog.models.organization_tombstone import tombstone_organization_record
from posthog.models.project import Project
from posthog.models.team import Team
from posthog.models.user import User


class TestTombstoneOrganizationRecord(BaseTest):
    def _bootstrap_doomed_org(self) -> tuple[Organization, User]:
        user = User.objects.create_user("doomed-member@example.com", None, "Doomed")
        organization, _, _ = Organization.objects.bootstrap(user, name="doomed org")
        organization.customer_id = "cus_tombstone_test"
        organization.save(update_fields=["customer_id"])
        OrganizationInvite.objects.create(organization=organization, target_email="invitee@example.com")
        OrganizationDomain.objects.create(organization=organization, domain="tombstone.example.com")
        return organization, user

    def test_replaces_the_row_with_a_deleted_marker(self):
        organization, user = self._bootstrap_doomed_org()
        original_created_at = organization.created_at

        tombstone_organization_record(str(organization.id))

        assert not Organization.objects.filter(id=organization.id).exists()
        tombstone = Organization.objects_including_soft_deleted.get(id=organization.id)
        assert bool(tombstone.deleted) is True
        assert tombstone.deleted_at is not None
        assert tombstone.name == ""
        assert tombstone.slug == f"deleted-{organization.id.hex}"
        assert tombstone.customer_id == "cus_tombstone_test"
        assert tombstone.created_at == original_created_at
        assert tombstone.is_active is False
        assert tombstone.is_not_active_reason == Organization.DeactivationReason.DELETED
        assert tombstone.is_pending_deletion is True
        assert tombstone.is_ai_data_processing_approved is False
        assert tombstone.is_ai_training_opted_in is False

        assert not OrganizationMembership.objects.filter(organization_id=organization.id).exists()
        assert not OrganizationInvite.objects.filter(organization_id=organization.id).exists()
        assert not OrganizationDomain.objects.filter(organization_id=organization.id).exists()
        assert not Project.objects.filter(organization_id=organization.id).exists()
        assert not Team.objects.filter(organization_id=organization.id).exists()

        user.refresh_from_db()
        assert user.current_organization_id is None
        assert user.current_team_id is None

    def test_is_idempotent(self):
        organization, _ = self._bootstrap_doomed_org()

        tombstone_organization_record(str(organization.id))
        first_deleted_at = Organization.objects_including_soft_deleted.get(id=organization.id).deleted_at
        tombstone_organization_record(str(organization.id))

        assert Organization.objects_including_soft_deleted.get(id=organization.id).deleted_at == first_deleted_at

    def test_frees_the_slug_for_reuse(self):
        organization, _ = self._bootstrap_doomed_org()
        original_slug = organization.slug

        tombstone_organization_record(str(organization.id))
        successor = Organization.objects.create(name="doomed org")

        assert successor.slug == original_slug

    def test_missing_organization_is_a_noop(self):
        tombstone_organization_record(str(uuid.uuid4()))

    def test_allocates_a_suffixed_slug_when_the_fixed_one_is_taken(self):
        organization, _ = self._bootstrap_doomed_org()
        fixed_slug = f"deleted-{organization.id.hex}"
        squatter = Organization.objects.create(name="squatter")
        Organization.objects.filter(id=squatter.id).update(slug=fixed_slug)

        tombstone_organization_record(str(organization.id))

        tombstone = Organization.objects_including_soft_deleted.get(id=organization.id)
        assert bool(tombstone.deleted) is True
        assert tombstone.slug != fixed_slug
        assert tombstone.slug.startswith("deleted-")
        assert Organization.objects.get(id=squatter.id).slug == fixed_slug

    def test_join_refuses_a_tombstoned_organization(self):
        organization, _ = self._bootstrap_doomed_org()
        tombstone_organization_record(str(organization.id))
        tombstone = Organization.objects_including_soft_deleted.get(id=organization.id)
        joiner = User.objects.create_user("late-joiner@example.com", None, "Late")

        with self.assertRaises(ValidationError):
            joiner.join(organization=tombstone)

        assert not OrganizationMembership.objects.filter(organization_id=organization.id).exists()

    def test_join_refuses_an_organization_pending_deletion(self):
        organization, _ = self._bootstrap_doomed_org()
        organization.is_pending_deletion = True
        organization.save(update_fields=["is_pending_deletion"])
        joiner = User.objects.create_user("pending-joiner@example.com", None, "Pending")

        with self.assertRaises(ValidationError):
            joiner.join(organization=organization)

        assert not OrganizationMembership.objects.filter(organization_id=organization.id, user=joiner).exists()

    def test_does_not_enqueue_member_billing_sync(self):
        organization, _ = self._bootstrap_doomed_org()

        with (
            patch("posthog.models.organization.is_cloud", return_value=True),
            patch("posthog.tasks.sync_billing.sync_members_to_billing") as sync_mock,
            self.captureOnCommitCallbacks(execute=True),
        ):
            tombstone_organization_record(str(organization.id))

        sync_mock.delay.assert_not_called()
