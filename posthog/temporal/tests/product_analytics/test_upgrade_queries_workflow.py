import pytest

from posthog.models.insight import Insight
from posthog.schema import NodeKind
from posthog.schema_migrations import LATEST_VERSIONS, MIGRATIONS, SchemaMigration
from posthog.temporal.product_analytics.upgrade_queries_workflow import (
    GetInsightsToMigrateActivityInputs,
    MigrateInsightsBatchActivityInputs,
    get_insights_to_migrate,
    migrate_insights_batch,
)
from posthog.test.base import QueryMatchingTest, snapshot_postgres_queries_context


class TrendsMigration(SchemaMigration):
    targets = {NodeKind.TRENDS_QUERY: 5}

    def transform(self, query):
        query["interval"] = "day"
        return query


@pytest.fixture(autouse=True)
def setup_migrations():
    LATEST_VERSIONS.clear()
    MIGRATIONS.clear()

    MIGRATIONS[NodeKind.TRENDS_QUERY] = {1: TrendsMigration()}
    # MIGRATIONS[NodeKind.EVENTS_NODE] = {1: EventsNodeMigration()}
    LATEST_VERSIONS[NodeKind.INSIGHT_VIZ_NODE] = 3
    LATEST_VERSIONS[NodeKind.TRENDS_QUERY] = 5
    LATEST_VERSIONS[NodeKind.EVENTS_NODE] = 7

    yield


def setup_insights(team):
    # all versions satisfied
    i1 = Insight.objects.create(
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
    i2 = Insight.objects.create(
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
    i3 = Insight.objects.create(
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
    i4 = Insight.objects.create(
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
    i5 = Insight.objects.create(team=team)

    # kind without migration (DataTableNode)
    i6 = Insight.objects.create(
        query={
            "kind": "DataTableNode",
        },
        team=team,
    )

    # no version (InsightVizNode)
    i7 = Insight.objects.create(
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
    i8 = Insight.objects.create(
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

    return i1, i2, i3, i4, i5, i6, i7, i8


class TestUpgradeQueriesWorkflow(QueryMatchingTest):
    @pytest.mark.django_db(transaction=True)
    def test_get_insights_to_migrate_activity(self, activity_environment, team):
        i1, i2, i3, i4, i5, i6, i7, i8 = setup_insights(team)
        inputs = GetInsightsToMigrateActivityInputs()

        with snapshot_postgres_queries_context(self):
            result = activity_environment.run(get_insights_to_migrate, inputs)

        expected_ids = [i2.id, i3.id, i4.id, i7.id, i8.id]
        assert sorted(result), expected_ids

    @pytest.mark.django_db(transaction=True)
    def test_migrate_insights_batch_activity(self, activity_environment, team):
        i1, i2, i3, i4, i5, i6, i7, i8 = setup_insights(team)
        inputs = MigrateInsightsBatchActivityInputs(
            insight_ids=[i2.id, i3.id, i4.id, i7.id, i8.id],
        )

        result = activity_environment.run(migrate_insights_batch, inputs)

        assert i3.query == "s"
