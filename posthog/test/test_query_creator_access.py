from posthog.test.base import BaseTest

from posthog.constants import AvailableFeature
from posthog.models import OrganizationMembership
from posthog.query_creator_access import assert_creator_can_run, creator_access_revoked

from products.access_control.backend.facade.user_access_control import UserAccessControlError
from products.access_control.backend.models.access_control import AccessControl


class TestCreatorAccessRevoked(BaseTest):
    def test_current_member_is_not_revoked(self) -> None:
        assert creator_access_revoked(self.user, self.team) is False

    def test_none_owner_is_revoked(self) -> None:
        assert creator_access_revoked(None, self.team) is True

    def test_deactivated_owner_is_revoked(self) -> None:
        self.user.is_active = False
        self.user.save()
        assert creator_access_revoked(self.user, self.team) is True

    def test_owner_removed_from_org_is_revoked(self) -> None:
        OrganizationMembership.objects.filter(organization=self.organization, user=self.user).delete()
        assert creator_access_revoked(self.user, self.team) is True

    def test_member_without_project_access_lost_access_rather_than_left(self) -> None:
        self.organization.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        self.organization.save()
        # Admins keep access to a private project, so the owner is demoted to a plain member first.
        self.organization_membership.level = OrganizationMembership.Level.MEMBER
        self.organization_membership.save()
        AccessControl.objects.create(
            team=self.team, resource="project", resource_id=str(self.team.id), access_level="none"
        )
        # Still in the org, so not "left": the recipients' message must say access, not membership.
        assert creator_access_revoked(self.user, self.team) is False
        with self.assertRaises(UserAccessControlError) as raised:
            assert_creator_can_run(self.user, self.team)
        assert raised.exception.resource == "project"
