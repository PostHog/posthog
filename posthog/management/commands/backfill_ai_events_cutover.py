from __future__ import annotations

import math
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from django.core.management.base import BaseCommand, CommandError

import structlog

from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.client.execute import sync_execute
from posthog.clickhouse.materialized_columns import get_materialized_column_for_property
from posthog.clickhouse.query_tagging import Product, tag_queries, tags_context
from posthog.hogql_queries.ai.ai_table_resolver import AI_EVENT_NAMES as _CANONICAL_AI_EVENT_NAMES
from posthog.models.ai_events.sql import TABLE_BASE_NAME, _strip_heavy_properties_sql

logger = structlog.get_logger(__name__)

TARGET_TABLE = TABLE_BASE_NAME  # Distributed ai_events — MV writes here, we match it
SOURCE_TABLE = "events"


def _trace_id_expr(source_alias: str = "") -> str:
    """Use the materialized column for $ai_trace_id when available (avoids scanning properties).

    Falls back to a JSON extraction so tests without the materialized column still work.
    Pass a non-empty `source_alias` when emitted inside a query that aliases the source
    table (e.g. `FROM events AS src`) so the column reference isn't shadowed by a SELECT-list
    alias of the same name.
    """
    col = get_materialized_column_for_property("events", "properties", "$ai_trace_id")
    prefix = f"{source_alias}." if source_alias else ""
    if col is not None:
        return f"{prefix}`{col.name}`"
    return f"JSONExtractString({prefix}properties, '$ai_trace_id')"


# Derived from the canonical frozenset so new $ai_* event types are picked up automatically.
AI_EVENT_NAMES = ", ".join(f"'{name}'" for name in sorted(_CANONICAL_AI_EVENT_NAMES))

SETTINGS = {"max_execution_time": 3600}

# Order matches _insert_select_sql's projection. `retention_days` is omitted —
# the target column has DEFAULT 30; `drop_date` is omitted — it's MATERIALIZED.
INSERT_COLUMNS = (
    "uuid, event, timestamp, team_id, distinct_id, person_id, properties, "
    "trace_id, session_id, parent_id, span_id, span_type, generation_id, experiment_id, "
    "span_name, trace_name, prompt_name, "
    "model, provider, framework, "
    "total_tokens, input_tokens, output_tokens, text_input_tokens, text_output_tokens, "
    "image_input_tokens, image_output_tokens, audio_input_tokens, audio_output_tokens, "
    "video_input_tokens, video_output_tokens, reasoning_tokens, "
    "cache_read_input_tokens, cache_creation_input_tokens, web_search_count, "
    "input_cost_usd, output_cost_usd, total_cost_usd, request_cost_usd, web_search_cost_usd, "
    "audio_cost_usd, image_cost_usd, video_cost_usd, "
    "latency, time_to_first_token, "
    "is_error, error, error_type, error_normalized, "
    "input, output, output_choices, input_state, output_state, tools, "
    "_timestamp, _offset, _partition"
)

DEFAULT_LOOKBACK_DAYS = 30  # matches ai_events TTL
DEFAULT_MAX_EVENTS_PER_TRACE = 1000  # reuse guard
DEFAULT_MAX_PERSONS_PER_TRACE = 10  # reuse guard


def _insert_select_sql(where_clause: str) -> str:
    """Render the ai_events MV's SELECT, sourced from `events` instead of Kafka.

    Events and the Kafka staging table carry the same raw $ai_* properties JSON,
    so the same JSONExtract* projections produce identical rows. Any divergence
    from the MV is a bug — this must be kept in sync with AI_EVENTS_MV_SQL in
    posthog/models/ai_events/sql.py.

    The `src.` qualifier on every reference to `properties` matters: the stripped
    projection is aliased `AS properties` and would shadow the source column
    otherwise, causing heavy-property JSONExtracts to read from the stripped blob
    and silently return NULL. See the matching comment on AI_EVENTS_MV_SQL.
    """
    stripped = _strip_heavy_properties_sql("src.properties")
    return f"""
SELECT
    src.uuid,
    src.event,
    src.timestamp,
    src.team_id,
    src.distinct_id,
    src.person_id,
    {stripped} AS properties,

    JSONExtractString(src.properties, '$ai_trace_id') AS trace_id,
    JSONExtract(src.properties, '$ai_session_id', 'Nullable(String)') AS session_id,
    JSONExtract(src.properties, '$ai_parent_id', 'Nullable(String)') AS parent_id,
    JSONExtract(src.properties, '$ai_span_id', 'Nullable(String)') AS span_id,
    JSONExtract(src.properties, '$ai_span_type', 'Nullable(String)') AS span_type,
    JSONExtract(src.properties, '$ai_generation_id', 'Nullable(String)') AS generation_id,
    JSONExtract(src.properties, '$ai_experiment_id', 'Nullable(String)') AS experiment_id,

    JSONExtract(src.properties, '$ai_span_name', 'Nullable(String)') AS span_name,
    JSONExtract(src.properties, '$ai_trace_name', 'Nullable(String)') AS trace_name,
    JSONExtract(src.properties, '$ai_prompt_name', 'Nullable(String)') AS prompt_name,

    JSONExtract(src.properties, '$ai_model', 'Nullable(String)') AS model,
    JSONExtract(src.properties, '$ai_provider', 'Nullable(String)') AS provider,
    JSONExtract(src.properties, '$ai_framework', 'Nullable(String)') AS framework,

    JSONExtract(src.properties, '$ai_total_tokens', 'Nullable(Int64)') AS total_tokens,
    JSONExtract(src.properties, '$ai_input_tokens', 'Nullable(Int64)') AS input_tokens,
    JSONExtract(src.properties, '$ai_output_tokens', 'Nullable(Int64)') AS output_tokens,
    JSONExtract(src.properties, '$ai_text_input_tokens', 'Nullable(Int64)') AS text_input_tokens,
    JSONExtract(src.properties, '$ai_text_output_tokens', 'Nullable(Int64)') AS text_output_tokens,
    JSONExtract(src.properties, '$ai_image_input_tokens', 'Nullable(Int64)') AS image_input_tokens,
    JSONExtract(src.properties, '$ai_image_output_tokens', 'Nullable(Int64)') AS image_output_tokens,
    JSONExtract(src.properties, '$ai_audio_input_tokens', 'Nullable(Int64)') AS audio_input_tokens,
    JSONExtract(src.properties, '$ai_audio_output_tokens', 'Nullable(Int64)') AS audio_output_tokens,
    JSONExtract(src.properties, '$ai_video_input_tokens', 'Nullable(Int64)') AS video_input_tokens,
    JSONExtract(src.properties, '$ai_video_output_tokens', 'Nullable(Int64)') AS video_output_tokens,
    JSONExtract(src.properties, '$ai_reasoning_tokens', 'Nullable(Int64)') AS reasoning_tokens,
    JSONExtract(src.properties, '$ai_cache_read_input_tokens', 'Nullable(Int64)') AS cache_read_input_tokens,
    JSONExtract(src.properties, '$ai_cache_creation_input_tokens', 'Nullable(Int64)') AS cache_creation_input_tokens,
    JSONExtract(src.properties, '$ai_web_search_count', 'Nullable(Int64)') AS web_search_count,

    JSONExtract(src.properties, '$ai_input_cost_usd', 'Nullable(Float64)') AS input_cost_usd,
    JSONExtract(src.properties, '$ai_output_cost_usd', 'Nullable(Float64)') AS output_cost_usd,
    JSONExtract(src.properties, '$ai_total_cost_usd', 'Nullable(Float64)') AS total_cost_usd,
    JSONExtract(src.properties, '$ai_request_cost_usd', 'Nullable(Float64)') AS request_cost_usd,
    JSONExtract(src.properties, '$ai_web_search_cost_usd', 'Nullable(Float64)') AS web_search_cost_usd,
    JSONExtract(src.properties, '$ai_audio_cost_usd', 'Nullable(Float64)') AS audio_cost_usd,
    JSONExtract(src.properties, '$ai_image_cost_usd', 'Nullable(Float64)') AS image_cost_usd,
    JSONExtract(src.properties, '$ai_video_cost_usd', 'Nullable(Float64)') AS video_cost_usd,

    JSONExtract(src.properties, '$ai_latency', 'Nullable(Float64)') AS latency,
    JSONExtract(src.properties, '$ai_time_to_first_token', 'Nullable(Float64)') AS time_to_first_token,

    if(JSONExtractRaw(src.properties, '$ai_is_error') IN ('true', '"true"'), 1, 0) AS is_error,
    JSONExtract(src.properties, '$ai_error', 'Nullable(String)') AS error,
    JSONExtract(src.properties, '$ai_error_type', 'Nullable(String)') AS error_type,
    JSONExtract(src.properties, '$ai_error_normalized', 'Nullable(String)') AS error_normalized,

    nullIf(JSONExtractRaw(src.properties, '$ai_input'), '') AS input,
    nullIf(JSONExtractRaw(src.properties, '$ai_output'), '') AS output,
    nullIf(JSONExtractRaw(src.properties, '$ai_output_choices'), '') AS output_choices,
    nullIf(JSONExtractRaw(src.properties, '$ai_input_state'), '') AS input_state,
    nullIf(JSONExtractRaw(src.properties, '$ai_output_state'), '') AS output_state,
    nullIf(JSONExtractRaw(src.properties, '$ai_tools'), '') AS tools,

    src._timestamp,
    src._offset,
    -- Source `events._partition` refers to a different Kafka topic's partition; carrying
    -- it through would be misleading. Zero is least misleading for backfilled rows.
    0 AS _partition
FROM {SOURCE_TABLE} AS src
WHERE {where_clause}
"""


@dataclass
class BackfillConfig:
    team_id: int
    flip_at: datetime
    lookback_days: int
    max_events_per_trace: int
    max_persons_per_trace: int
    use_offline_workload: bool
    num_retries: int = 10


@dataclass
class Identified:
    trace_ids: list[str]
    total_old_events: int
    traces_excluded_by_guards: int
    events_excluded_by_guards: int


def identify_straddling_traces(cfg: BackfillConfig) -> Identified:
    """Find trace_ids that have events in `events` before the flip AND in `ai_events` after.

    Applies reuse guards (event count, distinct persons) against the old-side counts to
    exclude trace_ids that are clearly not real LLM traces (broadcast message ids,
    hardcoded labels, workflow ids used across many users).
    """
    lookback_start = cfg.flip_at - _days(cfg.lookback_days)
    trace_id_expr = _trace_id_expr()

    query = f"""
    WITH
        old_pre_flip AS (
            SELECT
                {trace_id_expr} AS trace_id,
                count() AS old_event_count,
                uniqExact(distinct_id) AS persons
            FROM {SOURCE_TABLE}
            WHERE team_id = %(team_id)s
              AND event IN ({AI_EVENT_NAMES})
              AND timestamp >= %(lookback_start)s
              AND timestamp <  %(flip_at)s
              AND {trace_id_expr} != ''
            GROUP BY trace_id
        ),
        new_present AS (
            SELECT DISTINCT trace_id
            FROM {TARGET_TABLE}
            WHERE team_id = %(team_id)s
              AND timestamp >= %(flip_at)s
        ),
        straddling AS (
            SELECT old.trace_id AS trace_id, old.old_event_count AS old_event_count, old.persons AS persons
            FROM old_pre_flip AS old
            INNER JOIN new_present AS new ON old.trace_id = new.trace_id
        )
    SELECT
        groupArrayIf(trace_id, old_event_count <= %(max_events)s AND persons <= %(max_persons)s),
        sumIf(old_event_count, old_event_count <= %(max_events)s AND persons <= %(max_persons)s),
        countIf(old_event_count > %(max_events)s OR persons > %(max_persons)s),
        sumIf(old_event_count, old_event_count > %(max_events)s OR persons > %(max_persons)s)
    FROM straddling
    """
    params = {
        "team_id": cfg.team_id,
        "flip_at": cfg.flip_at,
        "lookback_start": lookback_start,
        "max_events": cfg.max_events_per_trace,
        "max_persons": cfg.max_persons_per_trace,
    }
    rows = sync_execute(
        query,
        params,
        workload=Workload.OFFLINE if cfg.use_offline_workload else Workload.DEFAULT,
        settings=SETTINGS,
    )
    trace_ids, total_events, excluded_traces, excluded_events = rows[0]
    return Identified(
        trace_ids=list(trace_ids or []),
        total_old_events=int(total_events or 0),
        traces_excluded_by_guards=int(excluded_traces or 0),
        events_excluded_by_guards=int(excluded_events or 0),
    )


def backfill_chunk(cfg: BackfillConfig, trace_ids: list[str], day_start: datetime, day_end: datetime) -> int:
    """INSERT ai_events rows for one day's slice, skipping any uuid already present.

    Returns rows inserted. Re-running is safe because the anti-join on uuid ensures
    we never double-write a row even if an event was dual-written post-flip with a
    backdated timestamp. ai_events is a plain MergeTree — there is no engine-level
    dedup, so the anti-join is the sole guarantee.
    """
    trace_id_expr = _trace_id_expr("src")
    where = f"""
        src.team_id = %(team_id)s
        AND src.event IN ({AI_EVENT_NAMES})
        AND src.timestamp >= %(day_start)s
        AND src.timestamp <  %(day_end)s
        AND {trace_id_expr} != ''
        AND {trace_id_expr} IN %(trace_ids)s
        AND src.uuid NOT IN (
            SELECT uuid
            FROM {TARGET_TABLE}
            WHERE team_id = %(team_id)s
              AND timestamp >= %(day_start)s
              AND timestamp <  %(day_end)s
              AND trace_id IN %(trace_ids)s
        )
    """
    insert_query = f"INSERT INTO {TARGET_TABLE} ({INSERT_COLUMNS}) {_insert_select_sql(where)}"
    params = {
        "team_id": cfg.team_id,
        "day_start": day_start,
        "day_end": day_end,
        "trace_ids": tuple(trace_ids),
    }
    for retries in range(cfg.num_retries + 1):
        try:
            result = sync_execute(
                insert_query,
                params,
                workload=Workload.OFFLINE if cfg.use_offline_workload else Workload.DEFAULT,
                settings=SETTINGS,
            )
            # sync_execute returns an int (written_rows from client.last_query.progress)
            # for INSERTs when available, else an empty list. See posthog/clickhouse/client/execute.py.
            return result if isinstance(result, int) else 0
        except Exception:
            if retries >= cfg.num_retries:
                logger.exception("backfill_chunk_failed", day_start=day_start.isoformat())
                raise
            seconds_delay = math.floor(10 * 1.68**retries)
            logger.warning(
                "backfill_chunk_retry",
                day_start=day_start.isoformat(),
                retry=retries + 1,
                max_retries=cfg.num_retries,
                delay_s=seconds_delay,
            )
            time.sleep(seconds_delay)
    raise RuntimeError("unreachable: retry loop exits via return or raise")


def run(cfg: BackfillConfig, *, dry_run: bool, print_counts: bool) -> None:
    with tags_context(product=Product.LLM_ANALYTICS):
        tag_queries(
            team_id=cfg.team_id,
            name="backfill_ai_events_cutover",
        )

        # Surface the parsed UTC timestamp so the operator can sanity-check the
        # --flip-at interpretation without relying on the --help text.
        logger.info("flip_at_parsed_utc", team_id=cfg.team_id, flip_at_utc=cfg.flip_at.isoformat())

        logger.info(
            "identification_start",
            team_id=cfg.team_id,
            flip_at=cfg.flip_at.isoformat(),
            lookback_days=cfg.lookback_days,
        )
        identified = identify_straddling_traces(cfg)
        logger.info(
            "identification_done",
            team_id=cfg.team_id,
            straddling_traces=len(identified.trace_ids),
            events_to_copy=identified.total_old_events,
            traces_excluded_by_guards=identified.traces_excluded_by_guards,
            events_excluded_by_guards=identified.events_excluded_by_guards,
        )

        if not identified.trace_ids:
            logger.info("no_straddling_traces_found")
            return

        if print_counts:
            _print_pre_post_counts(cfg, identified.trace_ids, label="before")

        if dry_run:
            sample = identified.trace_ids[:5]
            logger.info("dry_run_skipping_insert", sample_trace_ids=sample)
            return

        lookback_start = cfg.flip_at - _days(cfg.lookback_days)
        total_inserted = 0
        day = lookback_start.replace(hour=0, minute=0, second=0, microsecond=0)
        while day < cfg.flip_at:
            day_end = min(day + _days(1), cfg.flip_at)
            logger.info("backfill_day_start", day=day.date().isoformat())
            inserted = backfill_chunk(cfg, identified.trace_ids, day, day_end)
            total_inserted += inserted
            logger.info("backfill_day_done", day=day.date().isoformat(), rows_inserted=inserted)
            day = day_end

        logger.info("backfill_complete", team_id=cfg.team_id, total_rows_inserted=total_inserted)

        if print_counts:
            _print_pre_post_counts(cfg, identified.trace_ids, label="after")


def _print_pre_post_counts(cfg: BackfillConfig, trace_ids: list[str], *, label: str) -> None:
    query = f"""
    SELECT count() FROM {TARGET_TABLE}
    WHERE team_id = %(team_id)s
      AND trace_id IN %(trace_ids)s
      AND timestamp < %(flip_at)s
    """
    params = {"team_id": cfg.team_id, "trace_ids": tuple(trace_ids), "flip_at": cfg.flip_at}
    rows = sync_execute(
        query,
        params,
        workload=Workload.OFFLINE if cfg.use_offline_workload else Workload.DEFAULT,
        settings=SETTINGS,
    )
    logger.info(
        f"ai_events_pre_flip_rows_{label}",
        team_id=cfg.team_id,
        pre_flip_rows=int(rows[0][0] or 0),
    )


def _days(n: int) -> timedelta:
    return timedelta(days=n)


def _parse_flip_at(value: str) -> datetime:
    # Accept both "YYYY-MM-DD HH:MM:SS" and "YYYY-MM-DDTHH:MM:SS[±HH:MM]"
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            dt = datetime.strptime(value, fmt)
            return dt.astimezone(UTC) if dt.tzinfo else dt.replace(tzinfo=UTC)
        except ValueError:
            continue
    raise CommandError(f"Could not parse --flip-at={value!r}; use ISO8601 (UTC assumed if no tz)")


class Command(BaseCommand):
    help = "Backfill pre-flip ai_events rows for traces that straddle a team's dual-write flip."

    def add_arguments(self, parser):
        parser.add_argument("--team-id", type=int, required=True, help="team to backfill")
        parser.add_argument(
            "--flip-at",
            type=str,
            required=True,
            help="ISO8601 datetime of the dual-write flip for this team (UTC if no tz)",
        )
        parser.add_argument(
            "--lookback-days",
            type=int,
            default=DEFAULT_LOOKBACK_DAYS,
            help=f"how many days before --flip-at to scan (default {DEFAULT_LOOKBACK_DAYS}, matches ai_events TTL)",
        )
        parser.add_argument(
            "--max-events-per-trace",
            type=int,
            default=DEFAULT_MAX_EVENTS_PER_TRACE,
            help="reuse guard: exclude trace_ids with more pre-flip events than this",
        )
        parser.add_argument(
            "--max-persons-per-trace",
            type=int,
            default=DEFAULT_MAX_PERSONS_PER_TRACE,
            help="reuse guard: exclude trace_ids touched by more distinct persons than this",
        )
        parser.add_argument(
            "--live-run",
            action="store_true",
            help="actually run the INSERTs (default is identification + dry-run)",
        )
        parser.add_argument(
            "--no-use-offline-workload",
            action="store_true",
            help="run against default workload instead of offline replicas",
        )
        parser.add_argument("--print-counts", action="store_true", help="print row counts before and after")

    def handle(
        self,
        *,
        team_id: int,
        flip_at: str,
        lookback_days: int,
        max_events_per_trace: int,
        max_persons_per_trace: int,
        live_run: bool,
        no_use_offline_workload: bool,
        print_counts: bool,
        **_: object,
    ):
        cfg = BackfillConfig(
            team_id=team_id,
            flip_at=_parse_flip_at(flip_at),
            lookback_days=lookback_days,
            max_events_per_trace=max_events_per_trace,
            max_persons_per_trace=max_persons_per_trace,
            use_offline_workload=not no_use_offline_workload,
        )
        run(cfg, dry_run=not live_run, print_counts=print_counts)
