import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin

from posthog.clickhouse.client.execute import sync_execute
from posthog.management.commands.backfill_ai_events_cutover import (
    INSERT_COLUMNS,
    BackfillConfig,
    _parse_flip_at,
    identify_straddling_traces,
    run,
)
from posthog.models.ai_events.test_util import bulk_create_ai_events
from posthog.models.event.util import bulk_create_events

FLIP_AT = datetime(2026, 4, 15, 12, 0, 0, tzinfo=UTC)

# Columns that should match exactly between the backfill and the reference path (bulk_create_ai_events).
# Excluded because they differ by design, not by bug:
#   - uuid, timestamp: identity, not content
#   - properties: backfill strips heavy props, reference helper doesn't
#   - retention_days: reference helper sets 10000, backfill relies on DEFAULT 30
#   - _timestamp, _offset, _partition: ingestion metadata, zeroed in both but compared below
#   - drop_date: materialized from timestamp + retention_days; differs because retention_days differs
#   - person_id: random in fixtures
EXTRACTED_COLUMNS = [
    "trace_id",
    "session_id",
    "parent_id",
    "span_id",
    "span_type",
    "generation_id",
    "experiment_id",
    "span_name",
    "trace_name",
    "prompt_name",
    "model",
    "provider",
    "framework",
    "total_tokens",
    "input_tokens",
    "output_tokens",
    "text_input_tokens",
    "text_output_tokens",
    "image_input_tokens",
    "image_output_tokens",
    "audio_input_tokens",
    "audio_output_tokens",
    "video_input_tokens",
    "video_output_tokens",
    "reasoning_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
    "web_search_count",
    "input_cost_usd",
    "output_cost_usd",
    "total_cost_usd",
    "request_cost_usd",
    "web_search_cost_usd",
    "audio_cost_usd",
    "image_cost_usd",
    "video_cost_usd",
    "latency",
    "time_to_first_token",
    "is_error",
    "error",
    "error_type",
    "error_normalized",
    "input",
    "output",
    "output_choices",
    "input_state",
    "output_state",
    "tools",
]


def _make_cfg(team_id: int, **overrides: Any) -> BackfillConfig:
    base: dict[str, Any] = {
        "team_id": team_id,
        "flip_at": FLIP_AT,
        "lookback_days": 7,
        "max_events_per_trace": 1000,
        "max_persons_per_trace": 10,
        "use_offline_workload": False,
        "num_retries": 0,
    }
    base.update(overrides)
    return BackfillConfig(**base)


def _add_to_events_only(
    *,
    team,
    trace_id: str,
    timestamp: datetime,
    distinct_id: str = "user-1",
    extra_properties: dict | None = None,
) -> str:
    # Bypasses flush_persons_and_events' ai_events mirror — simulates a pre-flip write
    # that would only have gone to the shared `events` table.
    event_uuid = str(uuid.uuid4())
    props: dict = {"$ai_trace_id": trace_id, "$ai_model": "gpt-test"}
    if extra_properties:
        props.update(extra_properties)
    bulk_create_events(
        [
            {
                "event_uuid": event_uuid,
                "event": "$ai_generation",
                "team": team,
                "distinct_id": distinct_id,
                "timestamp": timestamp,
                "properties": props,
            }
        ]
    )
    return event_uuid


def _add_to_ai_events_only(
    *,
    team,
    trace_id: str,
    timestamp: datetime,
    distinct_id: str = "user-1",
    extra_properties: dict | None = None,
    event_uuid: str | None = None,
) -> str:
    event_uuid = event_uuid or str(uuid.uuid4())
    props: dict = {"$ai_trace_id": trace_id, "$ai_model": "gpt-test"}
    if extra_properties:
        props.update(extra_properties)
    bulk_create_ai_events(
        [
            {
                "event": "$ai_generation",
                "team": team,
                "distinct_id": distinct_id,
                "timestamp": timestamp,
                "event_uuid": event_uuid,
                "properties": props,
            }
        ]
    )
    return event_uuid


def _count_ai_events(team_id: int, trace_id: str) -> int:
    rows = sync_execute(
        "SELECT count() FROM ai_events WHERE team_id = %(team_id)s AND trace_id = %(trace_id)s",
        {"team_id": team_id, "trace_id": trace_id},
    )
    return int(rows[0][0])


def _uuids_for_trace(team_id: int, trace_id: str) -> set[str]:
    rows = sync_execute(
        "SELECT uuid FROM ai_events WHERE team_id = %(team_id)s AND trace_id = %(trace_id)s",
        {"team_id": team_id, "trace_id": trace_id},
    )
    return {str(row[0]) for row in rows}


class BackfillAiEventsCutoverTestCase(ClickhouseTestMixin, BaseTest):
    def test_straddling_trace_is_backfilled(self) -> None:
        trace_id = "straddler-1"
        pre_flip_uuid = _add_to_events_only(team=self.team, trace_id=trace_id, timestamp=FLIP_AT - timedelta(minutes=5))
        _add_to_events_only(team=self.team, trace_id=trace_id, timestamp=FLIP_AT + timedelta(minutes=2))
        _add_to_ai_events_only(team=self.team, trace_id=trace_id, timestamp=FLIP_AT + timedelta(minutes=2))

        assert _count_ai_events(self.team.id, trace_id) == 1  # only the post-flip event

        run(_make_cfg(self.team.id), dry_run=False, print_counts=False)

        pre_flip_rows = sync_execute(
            "SELECT uuid FROM ai_events WHERE team_id = %(team_id)s AND trace_id = %(trace_id)s AND timestamp < %(flip_at)s",
            {"team_id": self.team.id, "trace_id": trace_id, "flip_at": FLIP_AT},
        )
        assert [str(row[0]) for row in pre_flip_rows] == [pre_flip_uuid]

    def test_rerun_is_idempotent(self) -> None:
        trace_id = "straddler-2"
        _add_to_events_only(team=self.team, trace_id=trace_id, timestamp=FLIP_AT - timedelta(minutes=5))
        _add_to_events_only(team=self.team, trace_id=trace_id, timestamp=FLIP_AT - timedelta(minutes=3))
        _add_to_ai_events_only(team=self.team, trace_id=trace_id, timestamp=FLIP_AT + timedelta(minutes=2))

        run(_make_cfg(self.team.id), dry_run=False, print_counts=False)
        uuids_after_first = _uuids_for_trace(self.team.id, trace_id)
        run(_make_cfg(self.team.id), dry_run=False, print_counts=False)
        uuids_after_second = _uuids_for_trace(self.team.id, trace_id)

        assert len(uuids_after_first) == 3  # 2 pre-flip + 1 post-flip
        # Stronger than count equality: anti-join must preserve the exact uuid set
        # (count equality could coincide if one row got doubled and another dropped).
        assert uuids_after_second == uuids_after_first

    def test_reuse_guard_excludes_high_event_count(self) -> None:
        trace_id = "reused-message-id"
        for i in range(5):
            _add_to_events_only(
                team=self.team,
                trace_id=trace_id,
                timestamp=FLIP_AT - timedelta(minutes=10 + i),
            )
        _add_to_ai_events_only(team=self.team, trace_id=trace_id, timestamp=FLIP_AT + timedelta(minutes=2))

        identified = identify_straddling_traces(_make_cfg(self.team.id, max_events_per_trace=3))
        assert trace_id not in identified.trace_ids
        assert identified.traces_excluded_by_guards == 1
        assert identified.events_excluded_by_guards == 5

    def test_reuse_guard_excludes_high_person_count(self) -> None:
        trace_id = "broadcast-id"
        for i in range(5):
            _add_to_events_only(
                team=self.team,
                trace_id=trace_id,
                timestamp=FLIP_AT - timedelta(minutes=10 + i),
                distinct_id=f"user-{i}",
            )
        _add_to_ai_events_only(team=self.team, trace_id=trace_id, timestamp=FLIP_AT + timedelta(minutes=2))

        identified = identify_straddling_traces(_make_cfg(self.team.id, max_persons_per_trace=3))
        assert trace_id not in identified.trace_ids

    def test_trace_only_in_old_is_not_straddling(self) -> None:
        trace_id = "old-only"
        _add_to_events_only(team=self.team, trace_id=trace_id, timestamp=FLIP_AT - timedelta(minutes=5))

        identified = identify_straddling_traces(_make_cfg(self.team.id))
        assert trace_id not in identified.trace_ids

    def test_trace_only_in_new_is_not_straddling(self) -> None:
        trace_id = "new-only"
        _add_to_ai_events_only(team=self.team, trace_id=trace_id, timestamp=FLIP_AT + timedelta(minutes=5))

        identified = identify_straddling_traces(_make_cfg(self.team.id))
        assert trace_id not in identified.trace_ids

    def test_other_team_untouched(self) -> None:
        other_team = self.organization.teams.create(name="other")
        trace_id = "shared-id-across-teams"

        _add_to_events_only(team=other_team, trace_id=trace_id, timestamp=FLIP_AT - timedelta(minutes=5))
        _add_to_ai_events_only(team=other_team, trace_id=trace_id, timestamp=FLIP_AT + timedelta(minutes=2))

        # Baseline for both teams before the run.
        other_before = _uuids_for_trace(other_team.id, trace_id)
        self_before = _uuids_for_trace(self.team.id, trace_id)

        run(_make_cfg(self.team.id), dry_run=False, print_counts=False)

        # Belt-and-braces: both the target team (unaffected because it has no straddlers)
        # and the off-target team must be unchanged.
        assert _uuids_for_trace(other_team.id, trace_id) == other_before
        assert _uuids_for_trace(self.team.id, trace_id) == self_before

    def test_dry_run_does_not_insert(self) -> None:
        trace_id = "dry-run-trace"
        _add_to_events_only(team=self.team, trace_id=trace_id, timestamp=FLIP_AT - timedelta(minutes=5))
        _add_to_ai_events_only(team=self.team, trace_id=trace_id, timestamp=FLIP_AT + timedelta(minutes=2))

        run(_make_cfg(self.team.id), dry_run=True, print_counts=False)

        assert _count_ai_events(self.team.id, trace_id) == 1  # unchanged

    def test_heavy_columns_round_trip(self) -> None:
        # Named regression for the alias-shadowing bug: if `properties` in the SELECT is the
        # *stripped* projection instead of the source column, JSONExtractRaw for heavy keys
        # reads from a blob that no longer contains them and every heavy column comes out NULL.
        # This test fails loudly if that regression returns.
        trace_id = "heavy-trace"
        heavy_props = {
            "$ai_input": [{"role": "user", "content": "hello"}],
            "$ai_output": [{"role": "assistant", "content": "hi back"}],
            "$ai_output_choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}}],
            "$ai_input_state": {"step": "prompt"},
            "$ai_output_state": {"step": "reply"},
            "$ai_tools": [{"name": "lookup", "args": {}}],
        }
        pre_flip_uuid = _add_to_events_only(
            team=self.team,
            trace_id=trace_id,
            timestamp=FLIP_AT - timedelta(minutes=1),
            extra_properties=heavy_props,
        )
        _add_to_ai_events_only(team=self.team, trace_id=trace_id, timestamp=FLIP_AT + timedelta(minutes=1))

        run(_make_cfg(self.team.id), dry_run=False, print_counts=False)

        rows = sync_execute(
            "SELECT input, output, output_choices, input_state, output_state, tools FROM ai_events WHERE uuid = %(u)s",
            {"u": pre_flip_uuid},
        )
        assert len(rows) == 1, "backfilled row should exist"
        values = rows[0]
        assert all(v is not None for v in values), f"heavy columns must not be NULL: {values}"

    def test_backfill_matches_reference_extraction_for_fully_populated_event(self) -> None:
        # MV-parity test: write the SAME raw $ai_* properties through two independent paths
        # (the backfill's CH-side JSONExtract and bulk_create_ai_events' Python-side dict extraction)
        # and assert every extracted column matches. This is the highest-leverage single test —
        # any divergence in extraction (alias shadowing, type coercion, typo, missing column)
        # produces a diff.
        trace_id = "exhaustive-trace"
        full_props = {
            "$ai_trace_id": trace_id,
            "$ai_session_id": "sess-1",
            "$ai_parent_id": "parent-1",
            "$ai_span_id": "span-1",
            "$ai_span_type": "generation",
            "$ai_generation_id": "gen-1",
            "$ai_experiment_id": "exp-1",
            "$ai_span_name": "my span",
            "$ai_trace_name": "my trace",
            "$ai_prompt_name": "my prompt",
            "$ai_model": "gpt-4o",
            "$ai_provider": "openai",
            "$ai_framework": "langchain",
            "$ai_total_tokens": 300,
            "$ai_input_tokens": 100,
            "$ai_output_tokens": 200,
            "$ai_text_input_tokens": 80,
            "$ai_text_output_tokens": 180,
            "$ai_image_input_tokens": 10,
            "$ai_image_output_tokens": 5,
            "$ai_audio_input_tokens": 3,
            "$ai_audio_output_tokens": 2,
            "$ai_video_input_tokens": 1,
            "$ai_video_output_tokens": 1,
            "$ai_reasoning_tokens": 25,
            "$ai_cache_read_input_tokens": 50,
            "$ai_cache_creation_input_tokens": 40,
            "$ai_web_search_count": 4,
            "$ai_input_cost_usd": 0.0012,
            "$ai_output_cost_usd": 0.0034,
            "$ai_total_cost_usd": 0.0046,
            "$ai_request_cost_usd": 0.005,
            "$ai_web_search_cost_usd": 0.001,
            "$ai_audio_cost_usd": 0.0002,
            "$ai_image_cost_usd": 0.0003,
            "$ai_video_cost_usd": 0.0001,
            "$ai_latency": 1.23,
            "$ai_time_to_first_token": 0.34,
            "$ai_is_error": True,
            "$ai_error": "boom",
            "$ai_error_type": "TimeoutError",
            "$ai_error_normalized": "timeout",
            # Heavy values as dicts/lists — realistic and produce identical JSON via json.dumps
            # on both sides, avoiding the string-quoting asymmetry of JSONExtractRaw.
            "$ai_input": [{"role": "user", "content": "hello"}],
            "$ai_output": [{"role": "assistant", "content": "hi"}],
            "$ai_output_choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}}],
            "$ai_input_state": {"step": "prompt"},
            "$ai_output_state": {"step": "reply"},
            "$ai_tools": [{"name": "search", "description": "web search"}],
        }

        backfill_uuid = _add_to_events_only(
            team=self.team,
            trace_id=trace_id,
            timestamp=FLIP_AT - timedelta(minutes=1),
            extra_properties=full_props,
        )
        # Reference row written directly via the Python-path extraction (different code than
        # the CH-side JSONExtract). Lives alongside the backfilled row for column comparison.
        reference_uuid = _add_to_ai_events_only(
            team=self.team,
            trace_id=trace_id,
            timestamp=FLIP_AT - timedelta(minutes=1),
            extra_properties=full_props,
        )
        # Straddler marker so the backfill considers this trace.
        _add_to_ai_events_only(team=self.team, trace_id=trace_id, timestamp=FLIP_AT + timedelta(minutes=1))

        run(_make_cfg(self.team.id), dry_run=False, print_counts=False)

        cols_csv = ", ".join(EXTRACTED_COLUMNS)
        [backfilled] = sync_execute(
            f"SELECT {cols_csv} FROM ai_events WHERE uuid = %(u)s",
            {"u": backfill_uuid},
        )
        [reference] = sync_execute(
            f"SELECT {cols_csv} FROM ai_events WHERE uuid = %(u)s",
            {"u": reference_uuid},
        )

        # Heavy columns hold JSON strings; the two paths produce semantically-equal JSON
        # with different whitespace (CH's JSONExtractRaw normalizes; Python's json.dumps
        # adds spaces). Parse both sides before comparing so the test asserts semantic
        # equality, not byte-for-byte formatting equality.
        heavy_cols = {"input", "output", "output_choices", "input_state", "output_state", "tools"}

        def _normalize(col: str, value: object) -> object:
            if col in heavy_cols and isinstance(value, str):
                return json.loads(value)
            return value

        diffs = [
            (col, backfilled[i], reference[i])
            for i, col in enumerate(EXTRACTED_COLUMNS)
            if _normalize(col, backfilled[i]) != _normalize(col, reference[i])
        ]
        assert diffs == [], f"backfill diverged from reference extraction:\n{diffs}"

    def test_insert_columns_match_ai_events_schema(self) -> None:
        # Schema-drift canary: if someone adds a column to sharded_ai_events, the backfill's
        # explicit INSERT column list must be updated to match. Reads the live schema from
        # system.columns and asserts the set of non-MATERIALIZED columns equals the backfill's
        # target set (INSERT_COLUMNS + retention_days, which has DEFAULT 30).
        rows = sync_execute(
            """
            SELECT name, default_kind
            FROM system.columns
            WHERE table = 'sharded_ai_events'
              AND database = currentDatabase()
            """
        )
        assert rows, "sharded_ai_events schema should be visible in system.columns in tests"
        non_materialized = {name for name, default_kind in rows if default_kind != "MATERIALIZED"}

        insert_cols = {col.strip() for col in INSERT_COLUMNS.split(",")}
        # retention_days has DEFAULT 30; backfill relies on the default so it's omitted from INSERT.
        expected_columns = insert_cols | {"retention_days"}

        missing_from_insert = non_materialized - expected_columns
        extra_in_insert = expected_columns - non_materialized
        assert not missing_from_insert, (
            f"sharded_ai_events has columns the backfill doesn't write: {sorted(missing_from_insert)}. "
            "Add them to INSERT_COLUMNS and the SELECT in _insert_select_sql, or extend this canary's "
            "exception set if they're intentionally DEFAULT'ed."
        )
        assert not extra_in_insert, (
            f"Backfill writes columns that don't exist on sharded_ai_events: {sorted(extra_in_insert)}. "
            "Either the DDL was renamed/dropped, or INSERT_COLUMNS is stale."
        )


class TestFlipAtParsing:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("2026-04-15 12:00:00", datetime(2026, 4, 15, 12, 0, 0, tzinfo=UTC)),
            ("2026-04-15T12:00:00", datetime(2026, 4, 15, 12, 0, 0, tzinfo=UTC)),
            ("2026-04-15T12:00:00+00:00", datetime(2026, 4, 15, 12, 0, 0, tzinfo=UTC)),
        ],
    )
    def test_parses_common_formats(self, raw: str, expected: datetime) -> None:
        assert _parse_flip_at(raw) == expected
