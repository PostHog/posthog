from posthog.test.base import BaseTest


class TestDashboardInsightModel(BaseTest):
    def test_saving_the_model_generates_a_filter_hash(self):
        self.fail("needs to be written")
        # team: Team = Team.objects.create(id=7, organization=self.organization)
        # dashboard = Dashboard.objects.create(team=team)
        # insight = Insight.objects.create(
        #     team=team,
        #     filters={"events": [{"id": "$pageview"}], "properties": [{"key": "$browser", "value": "Mac OS X"}],},
        # )
        #
        # dashboard_insight: DashboardInsight = DashboardInsight.objects.create(dashboard=dashboard, insight=insight)
        #
        # self.assertEqual(dashboard_insight.filters_hash, "cache_a04161f5c9b35f28f105caba6f009cb7")

    def test_saving_the_model_generates_a_filter_hash_affected_by_dashboard_filters(self):
        self.fail("needs to be written")
        # team: Team = Team.objects.create(id=7, organization=self.organization)
        # dashboard = Dashboard.objects.create(team=team, filters={"date_from": "-3d", "date_to": None})
        # insight = Insight.objects.create(
        #     team=team,
        #     filters={"events": [{"id": "$pageview"}], "properties": [{"key": "$browser", "value": "Mac OS X"}],},
        # )
        #
        # dashboard_insight: DashboardInsight = DashboardInsight.objects.create(dashboard=dashboard, insight=insight)
        #
        # self.assertEqual(dashboard_insight.filters_hash, "cache_2a842d9a3d5c2a543cfb057e7af52f2f")
