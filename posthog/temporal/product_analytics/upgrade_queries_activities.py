import dataclasses
import textwrap
from typing import Optional

from django.db import connection
from temporalio import activity
from posthog.models import Insight
from posthog.schema_migrations.upgrade import upgrade
from posthog.temporal.common.logger import get_internal_logger
from posthog.schema_migrations import LATEST_VERSIONS


def _clause(kind: str, version: int) -> str:
    template = """
        query @? '$.** ? (
            @.kind == "{kind}" &&
            (!exists(@.version) || @.version == null || @.version < {version})
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


@activity.defn
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


@activity.defn
def migrate_insights_batch(inputs: MigrateInsightsBatchActivityInputs) -> list[int]:
    """Migrate a batch of insights to the latest version."""
    logger = get_internal_logger()
    failed: list[int] = []

    insights = Insight.objects_including_soft_deleted.filter(id__in=inputs.insight_ids)

    for insight in insights:
        try:
            insight.query = upgrade(insight.query)
            insight.save()
        except Exception as e:
            logger.exception(f"Error migrating insight {insight.id}: {str(e)}")
            failed.append(insight.id)

    return failed
