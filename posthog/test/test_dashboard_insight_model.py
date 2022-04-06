from posthog.models import Dashboard, Insight
from posthog.models.dashboard import DashboardInsight
from posthog.test.base import BaseTest


class TestDashboardInsightModel(BaseTest):
    def test_saving_the_model_generates_a_filter_hash(self):
        dashboard = Dashboard.objects.create(team=self.team)
        insight = Insight.objects.create(
            team=self.team,
            filters={"events": [{"id": "$pageview"}], "properties": [{"key": "$browser", "value": "Mac OS X"}],},
        )

        dashboard_insight: DashboardInsight = DashboardInsight.objects.create(dashboard=dashboard, insight=insight)

        self.assertEqual(dashboard_insight.filters_hash, "cache_fb5a5750179393024e866d2a06102feb")

    def test_saving_the_model_generates_a_filter_hash_affected_by_dashboard_filters(self):
        dashboard = Dashboard.objects.create(team=self.team, filters={"date_from": "-3d", "date_to": None})
        insight = Insight.objects.create(
            team=self.team,
            filters={"events": [{"id": "$pageview"}], "properties": [{"key": "$browser", "value": "Mac OS X"}],},
        )

        dashboard_insight: DashboardInsight = DashboardInsight.objects.create(dashboard=dashboard, insight=insight)

        self.assertEqual(dashboard_insight.filters_hash, "cache_1873ab2156058cfabafdc3c5d8a15a7a")
