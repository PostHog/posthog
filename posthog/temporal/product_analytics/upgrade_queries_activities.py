import json
import hashlib
import textwrap
import dataclasses
from typing import Any, Optional, cast

from django.db import connection
from django.db.models import Max

from structlog import get_logger
from temporalio import activity

from posthog.exceptions_capture import capture_exception
from posthog.redis import get_client
from posthog.schema_migrations import LATEST_VERSIONS, _discover_migrations
from posthog.schema_migrations.upgrade import upgrade

from products.product_analytics.backend.facade.models import Insight

LOGGER = get_logger(__name__)

CURSOR_REDIS_KEY_PREFIX = "product_analytics/upgrade_queries/cursor"
CURSOR_TTL_SECONDS = 60 * 60 * 24 * 30


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


def _cursor_key() -> str:
    """Keyed by the registered migrations, so a new migration reads an empty cursor and sweeps
    the whole table again."""
    versions = json.dumps(sorted((str(kind), version) for kind, version in LATEST_VERSIONS.items()))
    return f"{CURSOR_REDIS_KEY_PREFIX}/{hashlib.sha256(versions.encode()).hexdigest()[:16]}"


def _read_cursor() -> Optional[int]:
    try:
        raw = get_client().get(_cursor_key())
        return int(raw) if raw is not None else None
    except Exception:
        LOGGER.warning("upgrade_queries_cursor_read_failed", exc_info=True)
        return None


def _write_cursor(after_id: int) -> None:
    try:
        get_client().set(_cursor_key(), after_id, ex=CURSOR_TTL_SECONDS)
    except Exception:
        # A lost cursor only costs one more full sweep, so it must not fail the activity.
        LOGGER.warning("upgrade_queries_cursor_write_failed", exc_info=True)


def _max_insight_id() -> Optional[int]:
    return Insight.objects_including_soft_deleted.aggregate(Max("id"))["id__max"]


@activity.defn
def get_insights_to_migrate(inputs: GetInsightsToMigrateActivityInputs) -> GetInsightsToMigrateActivityResult:
    _discover_migrations()  # Populate LATEST_VERSIONS; this is the first activity in the workflow

    clauses = [_clause(k, v) for k, v in sorted(LATEST_VERSIONS.items())]
    if not clauses:
        # No migrations registered — guard against emitting `WHERE ()`, which Postgres rejects
        return GetInsightsToMigrateActivityResult(insight_ids=[], last_id=inputs.after_id)

    # There is no index that can serve the jsonpath predicate, so every row above the cursor is
    # read and tested. The scheduled workflow starts with no cursor, hence the resume from Redis:
    # without it each run walks the whole table again to prove there is nothing left to do.
    after_id = inputs.after_id if inputs.after_id is not None else _read_cursor()

    # Read the boundary before the scan. A MAX(id) read after the scan sees its own later snapshot,
    # so it counts insights that committed while the scan ran but were invisible to it. Parking
    # there would skip those rows on every later run. A boundary read first is never above a row the
    # scan could not have seen.
    boundary = _max_insight_id()

    after_clause = "" if after_id is None else f"\nAND id > {after_id}"
    where_body = ("\n   OR  ").join(clauses)
    sql = f"""
        SELECT id
        FROM posthog_dashboarditem
        WHERE query IS NOT NULL
        AND ({where_body}) {after_clause}
        ORDER BY id
        LIMIT {inputs.batch_size};
    """

    with connection.cursor() as cur:
        cur.execute(sql)
        ids = [row[0] for row in cur.fetchall()]

    if ids:
        # Written per page, not only at the end, so a run that exhausts its retries hands the
        # next one the position it reached instead of making it repeat the same walk.
        _write_cursor(ids[-1])
        return GetInsightsToMigrateActivityResult(insight_ids=ids, last_id=ids[-1])

    # The sweep is complete up to the boundary read before the scan. Park there so the next run
    # reads only the rows written since, without skipping any that committed mid-scan.
    if boundary is not None:
        _write_cursor(boundary)

    return GetInsightsToMigrateActivityResult(insight_ids=[], last_id=after_id)


@dataclasses.dataclass(frozen=True)
class MigrateInsightsBatchActivityInputs:
    """Inputs for the migrate insights batch activity."""

    insight_ids: list[int] = dataclasses.field()


@activity.defn
def migrate_insights_batch(inputs: MigrateInsightsBatchActivityInputs) -> list[int]:
    """Migrate a batch of insights to the latest version."""
    logger = LOGGER.bind()
    failed: list[int] = []

    insights = Insight.objects_including_soft_deleted.filter(id__in=inputs.insight_ids)

    for insight in insights:
        try:
            insight.query = upgrade(cast(dict[Any, Any], insight.query))
            # Narrow write: a full save would clobber concurrent user edits to other fields with
            # the stale values read above. Insight.save() appends query_metadata when regenerated.
            insight.save(update_fields=["query"])
        except Exception as e:
            logger.exception(f"Error migrating insight {insight.id}: {str(e)}")
            capture_exception(e, {"insight_id": insight.id, "team_id": insight.team_id})
            failed.append(insight.id)

    return failed
