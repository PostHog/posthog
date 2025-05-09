import pytest

from posthog.models.insight import Insight
from posthog.schema import NodeKind
from posthog.schema_migrations import LATEST_VERSIONS
from posthog.temporal.product_analytics.upgrade_queries_workflow import get_insights_to_migrate
from posthog.test.base import QueryMatchingTest


@pytest.fixture(autouse=True)
def setup_migrations():
    LATEST_VERSIONS.clear()
    # MIGRATIONS.clear()

    # MIGRATIONS[NodeKind.TRENDS_QUERY] = {1: SampleMigration()}
    # MIGRATIONS[NodeKind.EVENTS_NODE] = {1: EventsNodeMigration()}
    LATEST_VERSIONS[NodeKind.INSIGHT_VIZ_NODE] = 3
    LATEST_VERSIONS[NodeKind.TRENDS_QUERY] = 5
    LATEST_VERSIONS[NodeKind.EVENTS_NODE] = 7

    yield


class TestUpgradeQueriesWorkflow(QueryMatchingTest):
    @pytest.mark.django_db(transaction=True)
    def test_get_insights_to_migrate(self, activity_environment, team):
        # all versions satisfied
        Insight.objects.create(
            query={
                "kind": "InsightVizNode",
                "source": {
                    "kind": "TrendsQuery",
                    "series": [{"kind": "EventsNode", "event": "$pageview", "v": 8}],
                    "v": 6,
                },
                "v": 4,
            },
            team=team,
        )

        # matching top-level node (InsightVizNode)
        m1 = Insight.objects.create(
            query={
                "kind": "InsightVizNode",
                "source": {
                    "kind": "TrendsQuery",
                    "series": [{"kind": "EventsNode", "event": "$pageview", "v": 8}],
                    "v": 6,
                },
                "v": 3,
            },
            team=team,
        )

        # matching node in nested dict (TrendsQuery)
        m2 = Insight.objects.create(
            query={
                "kind": "InsightVizNode",
                "source": {
                    "kind": "TrendsQuery",
                    "series": [{"kind": "EventsNode", "event": "$pageview", "v": 8}],
                    "v": 5,
                },
                "v": 4,
            },
            team=team,
        )

        # matching node in nested list (EventsNode)
        m3 = Insight.objects.create(
            query={
                "kind": "InsightVizNode",
                "source": {
                    "kind": "TrendsQuery",
                    "series": [{"kind": "EventsNode", "event": "$pageview", "v": 7}],
                    "v": 6,
                },
                "v": 4,
            },
            team=team,
        )

        # no query
        Insight.objects.create(team=team)

        # kind without migration (DataTableNode)
        Insight.objects.create(
            query={
                "kind": "DataTableNode",
            },
            team=team,
        )

        # no version (InsightVizNode)
        m4 = Insight.objects.create(
            query={
                "kind": "InsightVizNode",
                "source": {
                    "kind": "TrendsQuery",
                    "series": [{"kind": "EventsNode", "event": "$pageview", "v": 8}],
                    "v": 6,
                },
            },
            team=team,
        )

        # none version (InsightVizNode)
        m5 = Insight.objects.create(
            query={
                "kind": "InsightVizNode",
                "source": {
                    "kind": "TrendsQuery",
                    "series": [{"kind": "EventsNode", "event": "$pageview", "v": 8}],
                    "v": 6,
                },
                "v": None,
            },
            team=team,
        )

        # with snapshot_postgres_queries_context(self):
        result = activity_environment.run(get_insights_to_migrate)

        expected_ids = [m1.id, m2.id, m3.id, m4.id, m5.id]
        assert sorted(result), expected_ids
