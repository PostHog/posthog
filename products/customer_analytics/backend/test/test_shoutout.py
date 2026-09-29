import pytest
from posthog.test.base import BaseTest

from django.db.utils import IntegrityError

from posthog.models import Team
from posthog.models.scoping import team_scope
from posthog.models.scoping.manager import TeamScopeError

from products.customer_analytics.backend.models import Shoutout, ShoutoutDelivery


class TestShoutoutModels(BaseTest):
    def setUp(self):
        super().setUp()
        self.other_team = Team.objects.create(organization=self.organization, name="Other")

    def test_objects_manager_is_fail_closed_and_team_scoped(self):
        # Set up one shoutout per team through the unscoped sibling.
        Shoutout.all_teams.create(team=self.team, message="ours")
        Shoutout.all_teams.create(team=self.other_team, message="theirs")

        # `objects` (TeamScopedManager) refuses to read without a team context — this is the
        # tenant-isolation guarantee that would silently break if the manager were swapped.
        with pytest.raises(TeamScopeError):
            list(Shoutout.objects.all())

        # Within a team context it returns only that team's rows...
        with team_scope(self.team.id, canonical=True):
            assert [s.message for s in Shoutout.objects.all()] == ["ours"]

        # ...while `all_teams` is the deliberate cross-team escape hatch.
        assert Shoutout.all_teams.count() == 2

    def test_delivery_channel_is_unique_per_shoutout(self):
        shoutout = Shoutout.all_teams.create(team=self.team, message="hi", total_channels=1)
        ShoutoutDelivery.all_teams.create(team=self.team, shoutout=shoutout, slack_channel_id="C1")

        # Re-posting the same channel to the same shoutout is rejected — this constraint is
        # what makes the async send task idempotent (no double-post on retry).
        with pytest.raises(IntegrityError):
            ShoutoutDelivery.all_teams.create(team=self.team, shoutout=shoutout, slack_channel_id="C1")

    def test_same_channel_allowed_across_shoutouts(self):
        # The uniqueness is scoped to (shoutout, channel), not the channel alone — the same
        # channel must be reachable by later shoutouts.
        first = Shoutout.all_teams.create(team=self.team, message="a")
        second = Shoutout.all_teams.create(team=self.team, message="b")
        ShoutoutDelivery.all_teams.create(team=self.team, shoutout=first, slack_channel_id="C1")
        ShoutoutDelivery.all_teams.create(team=self.team, shoutout=second, slack_channel_id="C1")

        assert ShoutoutDelivery.all_teams.filter(slack_channel_id="C1").count() == 2
