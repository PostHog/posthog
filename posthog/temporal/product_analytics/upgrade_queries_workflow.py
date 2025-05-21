import dataclasses
import datetime as dt
import json
import typing

from django.db import connection
import temporalio.workflow
from posthog.models import Insight
from posthog.schema_migrations.upgrade import upgrade
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.logger import get_internal_logger
from posthog.schema_migrations import LATEST_VERSIONS


@dataclasses.dataclass(frozen=True)
class GetInsightsToMigrateActivityInputs:
    """Inputs for the get insights to migrate activity."""

    batch_size: int = dataclasses.field(default=100)


@temporalio.activity.defn
def get_insights_to_migrate(inputs: GetInsightsToMigrateActivityInputs) -> list[int]:
    # TODO: Add index
    # TODO: Cross-join or run separately for each kind?
    # CREATE INDEX insight_query_gin_path
    # ON insight USING gin (query jsonb_path_ops);
    latest_versions = []
    for kind, version in LATEST_VERSIONS.items():
        latest_versions.append(f"('{kind}', {version})")

    sql = f"""
        WITH latest(kind, v_latest) AS (VALUES {','.join(latest_versions)})
        SELECT DISTINCT i.id
        FROM posthog_dashboarditem AS i
        CROSS JOIN latest AS l
        WHERE jsonb_path_exists(
            i.query,
            format(
                $$
                $.** ? (
                    @.kind == "%s" &&    /* kind matches */
                    (
                        !exists(@.v)     /* no v property */
                        || @.v == null   /* or v:null */
                        || @.v <= %s     /* or version ≤ latest */
                    )
                )
                $$,
                l.kind,
                l.v_latest
            )::jsonpath
        )
        LIMIT {inputs.batch_size};
    """

    with connection.cursor() as cur:
        cur.execute(sql)
        ids = [row[0] for row in cur.fetchall()]

    return ids


@dataclasses.dataclass(frozen=True)
class MigrateInsightsBatchActivityInputs:
    """Inputs for the migrate insights batch activity."""

    insight_ids: list[int] = dataclasses.field()


@temporalio.activity.defn
def migrate_insights_batch(inputs: MigrateInsightsBatchActivityInputs) -> None:
    """Migrate a batch of insights to the latest version."""
    logger = get_internal_logger()

    insights = Insight.objects.filter(id__in=inputs.insight_ids)

    for insight in insights:
        try:
            insight.query = upgrade(insight.query)
            insight.save()
        except Exception as e:
            logger.exception(f"Error migrating insight {insight.id}: {str(e)}")


@dataclasses.dataclass(frozen=True)
class UpgradeQueriesWorkflowInputs:
    """Inputs for the upgrade queries workflow."""

    batch_size: int = dataclasses.field(default=100)


@temporalio.workflow.defn(name="upgrade-queries")
class UpgradeQueriesWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> UpgradeQueriesWorkflowInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return UpgradeQueriesWorkflowInputs(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: UpgradeQueriesWorkflowInputs) -> None:
        insight_ids = await temporalio.workflow.execute_activity(
            get_insights_to_migrate,
            GetInsightsToMigrateActivityInputs(batch_size=inputs.batch_size),
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=temporalio.common.RetryPolicy(
                initial_interval=dt.timedelta(minutes=5),
                maximum_interval=dt.timedelta(minutes=60),
                maximum_attempts=3,
            ),
        )

        while len(insight_ids) > 0:
            await temporalio.workflow.execute_activity(
                migrate_insights_batch,
                MigrateInsightsBatchActivityInputs(insight_ids=insight_ids),
                start_to_close_timeout=dt.timedelta(minutes=10),
                retry_policy=temporalio.common.RetryPolicy(
                    initial_interval=dt.timedelta(minutes=10),
                    maximum_interval=dt.timedelta(minutes=60),
                    maximum_attempts=3,
                ),
            )
            insight_ids = await temporalio.workflow.execute_activity(
                get_insights_to_migrate,
                GetInsightsToMigrateActivityInputs(batch_size=inputs.batch_size),
                start_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=temporalio.common.RetryPolicy(
                    initial_interval=dt.timedelta(minutes=5),
                    maximum_interval=dt.timedelta(minutes=60),
                    maximum_attempts=3,
                ),
            )
