from posthog.test.base import BaseTest

from posthog.models import OrganizationMembership
from posthog.query_creator_access import creator_access_revoked


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
