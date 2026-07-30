from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.models.organization import Organization
from posthog.models.team import Team
from posthog.tasks.tasks import sync_user_product_lists_for_new_team


class TestSyncUserProductListsForNewTeam(BaseTest):
    def test_unreadable_organization_does_not_raise(self) -> None:
        # A read that can't see the freshly created org must not bubble up into signup
        with patch.object(Team, "all_users_with_access", side_effect=Organization.DoesNotExist):
            sync_user_product_lists_for_new_team(self.team.id)

    def test_missing_team_does_not_raise(self) -> None:
        sync_user_product_lists_for_new_team(-1)
