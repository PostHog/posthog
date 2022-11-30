from datetime import timedelta
from posthog.caching.insight_caching_state import LazyLoader
from posthog.models import Dashboard, DashboardTile, Insight, InsightViewed, Team, User
from posthog.test.base import BaseTest
from django.utils.timezone import now
from freezegun import freeze_time

filter_dict = {
    "events": [{"id": "$pageview"}],
    "properties": [{"key": "$browser", "value": "Mac OS X"}],
}


class TestLazyLoader(BaseTest):
    @freeze_time("2021-08-25T22:09:14.252Z")
    def test_recently_viewed_insights(self):
        insights = [Insight.objects.create(team=self.team) for _ in range(3)]
        user2 = User.objects.create(email="testuser@posthog.com")

        InsightViewed.objects.create(
            insight=insights[0],
            last_viewed_at=now() - timedelta(hours=50),
            user=self.user,
            team=self.team,
        )
        InsightViewed.objects.create(
            insight=insights[1],
            last_viewed_at=now() - timedelta(hours=50),
            user=self.user,
            team=self.team,
        )
        InsightViewed.objects.create(
            insight=insights[1],
            last_viewed_at=now() - timedelta(hours=35),
            user=user2,
            team=self.team,
        )
        InsightViewed.objects.create(
            insight=insights[2],
            last_viewed_at=now() - timedelta(hours=2),
            user=self.user,
            team=self.team,
        )

        self.assertEqual(LazyLoader().recently_viewed_insights, {insights[1].pk, insights[2].pk})
