import dataclasses
import datetime as dt

from django.db import connection
import temporalio.workflow
from posthog.models import Insight
from posthog.schema_migrations.upgrade import upgrade
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.logger import get_internal_logger
from posthog.schema_migrations import LATEST_VERSIONS


@temporalio.activity.defn
def get_insights_to_migrate() -> list[int]:
    # TODO: Add index
    # TODO: Cross-join or run separately for each kind?
    # CREATE INDEX insight_query_gin_path
    # ON insight USING gin (query jsonb_path_ops);
    latest_versions = []
    for kind, version in LATEST_VERSIONS.items():
        latest_versions.append(f"('{kind}', {version})")

    sql = f"""
        WITH latest(kind, v_latest) AS (
            VALUES
                {','.join(latest_versions)}
        )
        SELECT DISTINCT i.id
        FROM posthog_dashboarditem AS i
        CROSS JOIN latest AS l
        WHERE jsonb_path_exists(
            i.query,
            format(
                $$
                $.** ? (
                    @.kind == "%s" &&
                    ( @.v < %s || @.v == null )
                )
                $$,
                l.kind,
                l.v_latest
            )::jsonpath
        );
    """

    with connection.cursor() as cur:
        cur.execute(sql)
        ids = [row[0] for row in cur.fetchall()]

    return ids


@dataclasses.dataclass(frozen=True)
class MigrateInsightsBatchInputs:
    """Inputs for the migrate insights batch activity."""

    insight_ids: list[int] = dataclasses.field()


@temporalio.activity.defn
def migrate_insights_batch(inputs: MigrateInsightsBatchInputs) -> None:
    """Migrate a batch of insights to the latest version."""
    logger = get_internal_logger()

    insights = Insight.objects.filter(id__in=inputs.insight_ids)

    for insight in insights:
        try:
            insight.query = upgrade(insight.query)
            insight.save()
        except Exception as e:
            logger.exception(f"Error migrating insight {insight.id}: {str(e)}")


@temporalio.workflow.defn(name="upgrade-queries")
class UpgradeQueriesWorkflow(PostHogWorkflow):
    @temporalio.workflow.run
    async def run(self):
        # TODO: use a while-loop to process insights in batches
        insight_ids = await temporalio.workflow.execute_activity(
            get_insights_to_migrate,
            None,
            start_to_close_timeout=dt.timedelta(minutes=5),
            retry_policy=temporalio.common.RetryPolicy(
                initial_interval=dt.timedelta(minutes=5),
                maximum_interval=dt.timedelta(minutes=60),
                maximum_attempts=3,
            ),
        )

        for i in range(0, len(insight_ids)):
            batch = insight_ids[i : i + 100]

            temporalio.workflow.execute_activity(
                migrate_insights_batch,
                MigrateInsightsBatchInputs(insight_ids=[insight.id for insight in batch]),
                start_to_close_timeout=dt.timedelta(minutes=10),
                retry_policy=temporalio.common.RetryPolicy(
                    initial_interval=dt.timedelta(minutes=10),
                    maximum_interval=dt.timedelta(minutes=60),
                    maximum_attempts=3,
                ),
            )
