import pytest
from posthog.test.base import BaseTest

from django.db.utils import IntegrityError

from posthog.models import Team
from posthog.models.scoping import team_scope
from posthog.models.scoping.manager import TeamScopeError

from products.customer_analytics.backend.models import Announcement, AnnouncementDelivery


class TestAnnouncementModels(BaseTest):
    def setUp(self):
        super().setUp()
        self.other_team = Team.objects.create(organization=self.organization, name="Other")

    def test_objects_manager_is_fail_closed_and_team_scoped(self):
        # Set up one announcement per team through the unscoped sibling.
        Announcement.all_teams.create(team=self.team, message="ours")
        Announcement.all_teams.create(team=self.other_team, message="theirs")

        # `objects` (TeamScopedManager) refuses to read without a team context — this is the
        # tenant-isolation guarantee that would silently break if the manager were swapped.
        with pytest.raises(TeamScopeError):
            list(Announcement.objects.all())

        # Within a team context it returns only that team's rows...
        with team_scope(self.team.id, canonical=True):
            assert [a.message for a in Announcement.objects.all()] == ["ours"]

        # ...while `all_teams` is the deliberate cross-team escape hatch.
        assert Announcement.all_teams.count() == 2

    def test_delivery_channel_is_unique_per_announcement(self):
        announcement = Announcement.all_teams.create(team=self.team, message="hi", total_channels=1)
        AnnouncementDelivery.all_teams.create(team=self.team, announcement=announcement, slack_channel_id="C1")

        # Re-posting the same channel to the same announcement is rejected — this constraint is
        # what makes the async send task idempotent (no double-post on retry).
        with pytest.raises(IntegrityError):
            AnnouncementDelivery.all_teams.create(team=self.team, announcement=announcement, slack_channel_id="C1")

    def test_same_channel_allowed_across_announcements(self):
        # The uniqueness is scoped to (announcement, channel), not the channel alone — the same
        # channel must be reachable by later announcements.
        first = Announcement.all_teams.create(team=self.team, message="a")
        second = Announcement.all_teams.create(team=self.team, message="b")
        AnnouncementDelivery.all_teams.create(team=self.team, announcement=first, slack_channel_id="C1")
        AnnouncementDelivery.all_teams.create(team=self.team, announcement=second, slack_channel_id="C1")

        assert AnnouncementDelivery.all_teams.filter(slack_channel_id="C1").count() == 2
