import uuid
import pytest
from asgiref.sync import sync_to_async
from concurrent.futures import ThreadPoolExecutor

from django.conf import settings
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.models.insight import Insight
from posthog.schema import NodeKind
from posthog.schema_migrations import LATEST_VERSIONS, MIGRATIONS, SchemaMigration
from posthog.temporal.product_analytics.upgrade_queries_workflow import (
    UpgradeQueriesWorkflow,
    UpgradeQueriesWorkflowInputs,
)
from posthog.temporal.product_analytics.upgrade_queries_activities import (
    GetInsightsToMigrateActivityInputs,
    MigrateInsightsBatchActivityInputs,
    get_insights_to_migrate,
    migrate_insights_batch,
)
from posthog.test.base import QueryMatchingTest, snapshot_postgres_queries_context


class InsightVizMigration1(SchemaMigration):
    targets = {NodeKind.INSIGHT_VIZ_NODE: 1}

    def transform(self, query):
        return query


class InsightVizMigration2(SchemaMigration):
    targets = {NodeKind.INSIGHT_VIZ_NODE: 2}

    def transform(self, query):
        return query


class InsightVizMigration3(SchemaMigration):
    targets = {NodeKind.INSIGHT_VIZ_NODE: 3}

    def transform(self, query):
        return query


class TrendsMigration(SchemaMigration):
    targets = {NodeKind.TRENDS_QUERY: 5}

    def transform(self, query):
        query["interval"] = "day"
        return query


class EventsNodeMigration(SchemaMigration):
    targets = {NodeKind.EVENTS_NODE: 7}

    def transform(self, query):
        return query


@pytest.fixture(autouse=True)
def setup_migrations():
    LATEST_VERSIONS.clear()
    MIGRATIONS.clear()

    MIGRATIONS[NodeKind.INSIGHT_VIZ_NODE] = {
        1: InsightVizMigration1(),
        2: InsightVizMigration2(),
        3: InsightVizMigration3(),
    }
    MIGRATIONS[NodeKind.TRENDS_QUERY] = {5: TrendsMigration()}
    MIGRATIONS[NodeKind.EVENTS_NODE] = {7: EventsNodeMigration()}
    LATEST_VERSIONS[NodeKind.INSIGHT_VIZ_NODE] = 4
    LATEST_VERSIONS[NodeKind.TRENDS_QUERY] = 6
    LATEST_VERSIONS[NodeKind.EVENTS_NODE] = 8

    yield


def setup_insights(team):
    # all versions satisfied
    i1 = Insight.objects.create(
        query={
            "kind": "InsightVizNode",
            "source": {
                "kind": "TrendsQuery",
                "series": [{"kind": "EventsNode", "event": "$pageview", "version": 8}],
                "version": 6,
            },
            "version": 4,
        },
        team=team,
    )

    # matching top-level node (InsightVizNode)
    i2 = Insight.objects.create(
        query={
            "kind": "InsightVizNode",
            "source": {
                "kind": "TrendsQuery",
                "series": [{"kind": "EventsNode", "event": "$pageview", "version": 8}],
                "version": 6,
            },
            "version": 3,
        },
        team=team,
    )

    # matching node in nested dict (TrendsQuery)
    i3 = Insight.objects.create(
        query={
            "kind": "InsightVizNode",
            "source": {
                "kind": "TrendsQuery",
                "series": [{"kind": "EventsNode", "event": "$pageview", "version": 8}],
                "version": 5,
            },
            "version": 4,
        },
        team=team,
    )

    # matching node in nested list (EventsNode)
    i4 = Insight.objects.create(
        query={
            "kind": "InsightVizNode",
            "source": {
                "kind": "TrendsQuery",
                "series": [{"kind": "EventsNode", "event": "$pageview", "version": 7}],
                "version": 6,
            },
            "version": 4,
        },
        team=team,
        deleted=True,  # soft-deleted insights should be migrated too
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
                "series": [{"kind": "EventsNode", "event": "$pageview", "version": 8}],
                "version": 6,
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
                "series": [{"kind": "EventsNode", "event": "$pageview", "version": 8}],
                "version": 6,
            },
            "version": None,
        },
        team=team,
    )

    return i1, i2, i3, i4, i5, i6, i7, i8


class TestUpgradeQueriesWorkflow(QueryMatchingTest):
    @pytest.mark.django_db
    def test_get_insights_to_migrate_activity(self, activity_environment, team):
        i1, i2, i3, i4, i5, i6, i7, i8 = setup_insights(team)
        inputs = GetInsightsToMigrateActivityInputs()

        with snapshot_postgres_queries_context(self):
            result = activity_environment.run(get_insights_to_migrate, inputs)

        expected_ids = [i2.id, i3.id, i4.id, i7.id, i8.id]
        assert sorted(result.insight_ids) == expected_ids
        assert result.last_id == i8.id

    @pytest.mark.django_db
    def test_migrate_insights_batch_activity(self, activity_environment, team):
        i1, i2, i3, i4, i5, i6, i7, i8 = setup_insights(team)
        inputs = MigrateInsightsBatchActivityInputs(
            insight_ids=[i2.id, i3.id, i4.id, i7.id, i8.id],
        )

        activity_environment.run(migrate_insights_batch, inputs)

        # regular insight
        i3.refresh_from_db()
        assert i3.query["source"]["version"] == 6
        assert i3.query["source"]["interval"] == "day"

        # soft-deleted insight
        i4.refresh_from_db()
        assert i4.query["source"]["series"][0]["version"] == 8

    @pytest.mark.asyncio
    @pytest.mark.django_db(transaction=True)
    async def test_upgrade_queries_workflow(self, team):
        i1, i2, i3, i4, i5, i6, i7, i8 = await sync_to_async(setup_insights)(team)

        async with await WorkflowEnvironment.start_time_skipping() as activity_environment:
            async with Worker(
                activity_environment.client,
                task_queue=settings.TEMPORAL_TASK_QUEUE,
                workflows=[UpgradeQueriesWorkflow],
                activities=[get_insights_to_migrate, migrate_insights_batch],
                workflow_runner=UnsandboxedWorkflowRunner(),
                activity_executor=ThreadPoolExecutor(max_workers=50),
                debug_mode=True,  # turn off sandbox/deadlock detector
            ):
                await activity_environment.client.execute_workflow(
                    UpgradeQueriesWorkflow.run,
                    UpgradeQueriesWorkflowInputs(),
                    id=str(uuid.uuid4()),
                    task_queue=settings.TEMPORAL_TASK_QUEUE,
                )

        await sync_to_async(i3.refresh_from_db)()
        assert i3.query["source"]["version"] == 6
        assert i3.query["source"]["interval"] == "day"
