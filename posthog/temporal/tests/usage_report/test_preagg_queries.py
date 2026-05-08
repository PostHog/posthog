"""Functional tests for the preagg-table versions of the usage-report
event-count queries. The tests insert rows directly into the writable
preagg table — constructing aggregate states the same way the
materialized view does — and then call the helpers under test.

The legacy versions in `posthog/tasks/usage_report.py` already have
their own coverage in `posthog/tasks/test/test_usage_report.py`; these
tests prove the preagg helpers produce equivalent results from
pre-aggregated rows.
"""

from datetime import datetime
from typing import Any

from posthog.test.base import BaseTest, ClickhouseTestMixin

from posthog.clickhouse.client import sync_execute
from posthog.models.usage_report_events_preagg.sql import (
    DISTRIBUTED_USAGE_REPORT_EVENTS_PREAGG_TABLE_SQL,
    SHARDED_USAGE_REPORT_EVENTS_PREAGG_TABLE,
    SHARDED_USAGE_REPORT_EVENTS_PREAGG_TABLE_SQL,
    WRITABLE_USAGE_REPORT_EVENTS_PREAGG_TABLE,
    WRITABLE_USAGE_REPORT_EVENTS_PREAGG_TABLE_SQL,
)
from posthog.temporal.usage_report.preagg_queries import (
    get_all_event_metrics_in_period_from_preagg,
    get_teams_with_billable_enhanced_persons_event_count_in_period_from_preagg,
    get_teams_with_billable_event_count_in_period_from_preagg,
)

# Picked far above any seeded test team so leftover rows from other
# tests sharing the dev/test ClickHouse don't bleed into our queries.
_TEAM_A = 9_900_001
_TEAM_B = 9_900_002

# Match production semantics: `get_previous_day` returns
# `(start_of_day, end_of_day at 23:59:59.999999)` — both within the same
# calendar day. The preagg helpers must include the end day.
_BEGIN = datetime(2026, 5, 4, 0, 0, 0)
_END = datetime(2026, 5, 4, 23, 59, 59, 999999)
_DAY = "2026-05-04"


def _evt(
    *,
    team_id: int,
    event: str,
    distinct_id: str,
    uuid: str,
    person_mode: str = "full",
    lib: str = "web",
    day: str = _DAY,
) -> dict[str, Any]:
    return {
        "date": day,
        "team_id": team_id,
        "person_mode": person_mode,
        "lib": lib,
        "event": event,
        "distinct_id": distinct_id,
        "uuid": uuid,
    }


def _as_dict(rows: Any) -> dict[int, int]:
    return {int(team_id): int(count) for team_id, count in rows}


class _PreaggQueriesBase(ClickhouseTestMixin, BaseTest):
    """Shared setup. Migrations target AUX/INGESTION clusters which
    aren't always present in the local test cluster, so we recreate the
    tables our queries touch the same way `test_usage_report_events_preagg_mv`
    does — that's the established pattern for testing this MV.
    """

    def setUp(self) -> None:
        sync_execute(SHARDED_USAGE_REPORT_EVENTS_PREAGG_TABLE_SQL())
        sync_execute(DISTRIBUTED_USAGE_REPORT_EVENTS_PREAGG_TABLE_SQL())
        sync_execute(WRITABLE_USAGE_REPORT_EVENTS_PREAGG_TABLE_SQL())
        # TRUNCATE rather than DELETE: lightweight DELETE is async and
        # was racing inserts inside individual test methods, so a
        # date-sensitive assertion (`test_period_filter_is_half_open`)
        # would see no rows. The preagg table is dedicated to this
        # workflow, so wiping the whole thing between tests is safe.
        sync_execute(f"TRUNCATE TABLE {SHARDED_USAGE_REPORT_EVENTS_PREAGG_TABLE}")
        super().setUp()

    def _insert_preagg_events(self, events: list[dict[str, Any]]) -> None:
        """Insert raw billable-event tuples into the writable preagg
        table, aggregating them into the same `distinct_events_unique` /
        `event_count` states the MV would produce.

        Each item in `events` is a single occurrence:
            {date, team_id, person_mode, lib, event, distinct_id, uuid}

        The UNION ALL is grouped by (date, team_id, person_mode, lib,
        event) so collisions on the unique tuple inside one bucket
        dedupe via `uniqExactState`, exactly mirroring the MV's
        behavior.
        """
        if not events:
            return

        union_parts: list[str] = []
        params: dict[str, Any] = {}
        for i, e in enumerate(events):
            union_parts.append(
                f"""
                SELECT
                    toDate(%(date_{i})s) AS date,
                    toInt64(%(team_id_{i})s) AS team_id,
                    %(person_mode_{i})s AS person_mode,
                    %(lib_{i})s AS lib,
                    %(event_{i})s AS event,
                    %(distinct_id_{i})s AS distinct_id,
                    %(uuid_{i})s AS uuid
                """
            )
            params[f"date_{i}"] = e["date"]
            params[f"team_id_{i}"] = e["team_id"]
            params[f"person_mode_{i}"] = e["person_mode"]
            params[f"lib_{i}"] = e["lib"]
            params[f"event_{i}"] = e["event"]
            params[f"distinct_id_{i}"] = e["distinct_id"]
            params[f"uuid_{i}"] = e["uuid"]

        union_sql = " UNION ALL ".join(union_parts)

        sync_execute(
            f"""
            INSERT INTO {WRITABLE_USAGE_REPORT_EVENTS_PREAGG_TABLE}
            SELECT
                date,
                team_id,
                person_mode,
                lib,
                event,
                uniqExactState((cityHash64(distinct_id), cityHash64(uuid), cityHash64(event)))
                    AS distinct_events_unique,
                sumState(toUInt64(1)) AS event_count
            FROM ({union_sql})
            GROUP BY date, team_id, person_mode, lib, event
            """,
            params,
        )


class TestBillableEventCountFromPreagg(_PreaggQueriesBase):
    def test_counts_distinct_events_per_team(self) -> None:
        self._insert_preagg_events(
            [
                _evt(team_id=_TEAM_A, event="pageview", distinct_id="u1", uuid="a-1"),
                _evt(team_id=_TEAM_A, event="pageview", distinct_id="u2", uuid="a-2"),
                _evt(team_id=_TEAM_A, event="click", distinct_id="u1", uuid="a-3"),
                _evt(team_id=_TEAM_B, event="pageview", distinct_id="u3", uuid="b-1"),
            ]
        )

        result = _as_dict(get_teams_with_billable_event_count_in_period_from_preagg(_BEGIN, _END))

        self.assertEqual(result, {_TEAM_A: 3, _TEAM_B: 1})

    def test_replayed_events_dedupe_within_a_day(self) -> None:
        # Same (distinct_id, uuid, event) twice on the same day should
        # collapse to 1 — that's the whole reason `uniqExactState` is
        # used over a plain count.
        self._insert_preagg_events(
            [
                _evt(team_id=_TEAM_A, event="pageview", distinct_id="u1", uuid="a-1"),
                _evt(team_id=_TEAM_A, event="pageview", distinct_id="u1", uuid="a-1"),
                _evt(team_id=_TEAM_A, event="pageview", distinct_id="u2", uuid="a-2"),
            ]
        )

        result = _as_dict(get_teams_with_billable_event_count_in_period_from_preagg(_BEGIN, _END))

        self.assertEqual(result, {_TEAM_A: 2})

    def test_excludes_billing_blocklist(self) -> None:
        # The legacy query excludes feature-flag bookkeeping, survey
        # bookkeeping, and `$exception`. The preagg version must too —
        # otherwise customers get double-billed for events also covered
        # by other meters.
        self._insert_preagg_events(
            [
                _evt(team_id=_TEAM_A, event="pageview", distinct_id="u1", uuid="a-1"),
                _evt(team_id=_TEAM_A, event="$feature_flag_called", distinct_id="u1", uuid="a-2"),
                _evt(team_id=_TEAM_A, event="survey sent", distinct_id="u1", uuid="a-3"),
                _evt(team_id=_TEAM_A, event="survey shown", distinct_id="u1", uuid="a-4"),
                _evt(team_id=_TEAM_A, event="survey dismissed", distinct_id="u1", uuid="a-5"),
                _evt(team_id=_TEAM_A, event="$exception", distinct_id="u1", uuid="a-6"),
                _evt(team_id=_TEAM_A, event="$ai_generation", distinct_id="u1", uuid="a-7"),
            ]
        )

        result = _as_dict(get_teams_with_billable_event_count_in_period_from_preagg(_BEGIN, _END))

        self.assertEqual(result, {_TEAM_A: 1})

    def test_filters_to_single_day(self) -> None:
        # Helper is single-day only: only events whose `date` matches
        # `toDate(begin)` are counted. Events on neighboring days must
        # not bleed in, so the daily workflow can chain without
        # double-counting boundaries.
        self._insert_preagg_events(
            [
                _evt(team_id=_TEAM_A, event="pageview", distinct_id="u1", uuid="a-1", day="2026-05-03"),
                _evt(team_id=_TEAM_A, event="pageview", distinct_id="u2", uuid="a-2", day="2026-05-04"),
                _evt(team_id=_TEAM_A, event="pageview", distinct_id="u3", uuid="a-3", day="2026-05-05"),
            ]
        )

        result = _as_dict(get_teams_with_billable_event_count_in_period_from_preagg(_BEGIN, _END))

        self.assertEqual(result, {_TEAM_A: 1})


class TestEnhancedPersonsEventCountFromPreagg(_PreaggQueriesBase):
    def test_filters_to_full_and_force_upgrade_modes(self) -> None:
        self._insert_preagg_events(
            [
                _evt(team_id=_TEAM_A, event="pageview", distinct_id="u1", uuid="a-1", person_mode="full"),
                _evt(team_id=_TEAM_A, event="pageview", distinct_id="u2", uuid="a-2", person_mode="propertyless"),
                _evt(team_id=_TEAM_A, event="pageview", distinct_id="u3", uuid="a-3", person_mode="force_upgrade"),
            ]
        )

        result = _as_dict(get_teams_with_billable_enhanced_persons_event_count_in_period_from_preagg(_BEGIN, _END))

        # `full` and `force_upgrade` count, `propertyless` doesn't.
        self.assertEqual(result, {_TEAM_A: 2})

    def test_excludes_billing_blocklist(self) -> None:
        self._insert_preagg_events(
            [
                _evt(team_id=_TEAM_A, event="pageview", distinct_id="u1", uuid="a-1"),
                _evt(team_id=_TEAM_A, event="$ai_generation", distinct_id="u1", uuid="a-2"),
                _evt(team_id=_TEAM_A, event="$exception", distinct_id="u1", uuid="a-3"),
            ]
        )

        result = _as_dict(get_teams_with_billable_enhanced_persons_event_count_in_period_from_preagg(_BEGIN, _END))

        self.assertEqual(result, {_TEAM_A: 1})


class TestAllEventMetricsFromPreagg(_PreaggQueriesBase):
    def test_buckets_by_event_prefix_and_lib(self) -> None:
        self._insert_preagg_events(
            [
                _evt(team_id=_TEAM_A, event="helicone_request", distinct_id="u1", uuid="a-1", lib="web"),
                _evt(team_id=_TEAM_A, event="langfuse_trace", distinct_id="u2", uuid="a-2", lib="web"),
                _evt(team_id=_TEAM_A, event="keywords_ai_event", distinct_id="u3", uuid="a-3", lib="web"),
                _evt(team_id=_TEAM_A, event="traceloop_span", distinct_id="u4", uuid="a-4", lib="web"),
                _evt(team_id=_TEAM_A, event="pageview", distinct_id="u5", uuid="a-5", lib="web"),
                _evt(team_id=_TEAM_A, event="pageview", distinct_id="u6", uuid="a-6", lib="js"),
                _evt(team_id=_TEAM_A, event="pageview", distinct_id="u7", uuid="a-7", lib="posthog-node"),
                _evt(team_id=_TEAM_A, event="pageview", distinct_id="u8", uuid="a-8", lib="posthog-android"),
                _evt(team_id=_TEAM_A, event="pageview", distinct_id="u9", uuid="a-9", lib="posthog-ios"),
                _evt(team_id=_TEAM_A, event="pageview", distinct_id="u10", uuid="a-10", lib="posthog-server"),
                _evt(team_id=_TEAM_A, event="pageview", distinct_id="u11", uuid="a-11", lib="posthog-rs"),
                # Unknown lib — should be bucketed `other` and dropped.
                _evt(team_id=_TEAM_A, event="pageview", distinct_id="u12", uuid="a-12", lib="some-mystery"),
            ]
        )

        result = get_all_event_metrics_in_period_from_preagg(_BEGIN, _END)

        # Each provider/library-prefix bucket has exactly one event.
        self.assertEqual(_as_dict(result["helicone_events"]), {_TEAM_A: 1})
        self.assertEqual(_as_dict(result["langfuse_events"]), {_TEAM_A: 1})
        self.assertEqual(_as_dict(result["keywords_ai_events"]), {_TEAM_A: 1})
        self.assertEqual(_as_dict(result["traceloop_events"]), {_TEAM_A: 1})
        self.assertEqual(_as_dict(result["web_events"]), {_TEAM_A: 1})
        self.assertEqual(_as_dict(result["web_lite_events"]), {_TEAM_A: 1})
        self.assertEqual(_as_dict(result["node_events"]), {_TEAM_A: 1})
        self.assertEqual(_as_dict(result["android_events"]), {_TEAM_A: 1})
        self.assertEqual(_as_dict(result["ios_events"]), {_TEAM_A: 1})
        self.assertEqual(_as_dict(result["rust_events"]), {_TEAM_A: 1})
        # `posthog-server` collapses into `java_events` per the
        # legacy bucketing.
        self.assertEqual(_as_dict(result["java_events"]), {_TEAM_A: 1})

    def test_metric_returns_total_count_not_distinct(self) -> None:
        # `event_count` is a `sumState` of one-per-row, so two rows for
        # the same (distinct_id, uuid) on the same day still sum to 2.
        # The legacy version uses `count(1)`, so this matches.
        self._insert_preagg_events(
            [
                _evt(team_id=_TEAM_A, event="pageview", distinct_id="u1", uuid="a-1", lib="web"),
                _evt(team_id=_TEAM_A, event="pageview", distinct_id="u1", uuid="a-1", lib="web"),
            ]
        )

        result = get_all_event_metrics_in_period_from_preagg(_BEGIN, _END)

        self.assertEqual(_as_dict(result["web_events"]), {_TEAM_A: 2})

    def test_returns_empty_lists_for_unused_buckets(self) -> None:
        self._insert_preagg_events(
            [
                _evt(team_id=_TEAM_A, event="pageview", distinct_id="u1", uuid="a-1", lib="web"),
            ]
        )

        result = get_all_event_metrics_in_period_from_preagg(_BEGIN, _END)

        # Every metric key must be present even if empty — the
        # aggregator iterates over the multi-keys mapping and would
        # KeyError otherwise.
        for key in (
            "helicone_events",
            "langfuse_events",
            "keywords_ai_events",
            "traceloop_events",
            "node_events",
            "android_events",
            "ios_events",
            "flutter_events",
            "go_events",
            "java_events",
            "react_native_events",
            "ruby_events",
            "python_events",
            "php_events",
            "dotnet_events",
            "elixir_events",
            "unity_events",
            "rust_events",
            "web_lite_events",
        ):
            self.assertEqual(result[key], [])
