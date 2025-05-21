import dataclasses
import datetime as dt
import json
import textwrap
from typing import Optional

from django.db import connection
import temporalio.workflow
from posthog.models import Insight
from posthog.schema_migrations.upgrade import upgrade
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.logger import get_internal_logger
from posthog.schema_migrations import LATEST_VERSIONS


def _clause(kind: str, version: int) -> str:
    template = """
        query @? '$.** ? (
            @.kind == "{kind}" &&
            (!exists(@.v) || @.v == null || @.v <= {version})
        )'"""
    return textwrap.dedent(template.format(kind=kind, version=version)).strip()


@dataclasses.dataclass(frozen=True)
class GetInsightsToMigrateActivityInputs:
    """Inputs for the get insights to migrate activity."""

    batch_size: int = dataclasses.field(default=100)
    after_id: Optional[int] = dataclasses.field(default=None)


@dataclasses.dataclass(frozen=True)
class GetInsightsToMigrateActivityResult:
    """Result of the get insights to migrate activity."""

    insight_ids: list[int]
    last_id: Optional[int]


@temporalio.activity.defn
def get_insights_to_migrate(inputs: GetInsightsToMigrateActivityInputs) -> GetInsightsToMigrateActivityResult:
    clauses = [_clause(k, v) for k, v in sorted(LATEST_VERSIONS.items())]
    after_clause = "" if inputs.after_id is None else f"\nAND id > {inputs.after_id}"
    where_body = ("\n   OR  ").join(clauses)
    sql = f"""
        SELECT DISTINCT id
        FROM posthog_dashboarditem
        WHERE ({where_body}) {after_clause}
        ORDER BY id
        LIMIT {inputs.batch_size};
    """

    with connection.cursor() as cur:
        cur.execute(sql)
        ids = [row[0] for row in cur.fetchall()]
    last_id = ids[-1] if ids else inputs.after_id

    return GetInsightsToMigrateActivityResult(insight_ids=ids, last_id=last_id)


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


@dataclasses.dataclass
class WorkflowState:
    after_id: Optional[int]
    migrated: int


@temporalio.workflow.defn(name="upgrade-queries")
class UpgradeQueriesWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> UpgradeQueriesWorkflowInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return UpgradeQueriesWorkflowInputs(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: UpgradeQueriesWorkflowInputs) -> None:
        state = WorkflowState(
            after_id=None,
            migrated=0,
        )

        while True:
            page = await temporalio.workflow.execute_activity(
                get_insights_to_migrate,
                GetInsightsToMigrateActivityInputs(batch_size=inputs.batch_size, after_id=state.after_id),
                start_to_close_timeout=dt.timedelta(minutes=5),
                retry_policy=temporalio.common.RetryPolicy(
                    initial_interval=dt.timedelta(minutes=5),
                    maximum_interval=dt.timedelta(minutes=60),
                    maximum_attempts=3,
                ),
            )

            if not page.insight_ids:
                return  # finished

            await temporalio.workflow.execute_activity(
                migrate_insights_batch,
                MigrateInsightsBatchActivityInputs(insight_ids=page.insight_ids),
                start_to_close_timeout=dt.timedelta(minutes=10),
                retry_policy=temporalio.common.RetryPolicy(
                    initial_interval=dt.timedelta(minutes=10),
                    maximum_interval=dt.timedelta(minutes=60),
                    maximum_attempts=3,
                ),
            )

            state.after_id = page.last_id
            state.migrated += len(page.insight_ids)
