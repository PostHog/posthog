import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from parameterized import parameterized

from posthog.hogql_queries.ai.ai_table_resolver import query_ai_events
from posthog.models.ai_events.test_util import bulk_create_ai_events

from products.ai_observability.backend.backfill_candidates import count_backfill_candidates, fetch_backfill_candidates
from products.ai_observability.backend.models.evaluations import Evaluation

CANDIDATES_MODULE = "products.ai_observability.backend.backfill_candidates"

BASE = datetime(2026, 8, 1, 12, tzinfo=UTC)
WINDOW_START = BASE - timedelta(hours=1)
WINDOW_END = BASE + timedelta(days=1)


def _generation_uuid(index: int) -> str:
    return str(uuid.UUID(int=index))


class TestBackfillCandidates(ClickhouseTestMixin, APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.evaluation = Evaluation.objects.create(
            team=self.team,
            name="e",
            evaluation_type="hog",
            evaluation_config={"source": "return true"},
            output_type="boolean",
            output_config={},
            conditions=[],
        )
        # (label, trace, offset, model). One trace carries two generations, so trace and session
        # grouping collapses where the generation target does not.
        self.fixture = [
            ("g1", "t1", timedelta(0), "gpt-4o"),
            ("g2", "t1", timedelta(minutes=1), "gpt-4o"),
            ("g3", "t2", timedelta(hours=1), "gpt-4o-mini"),
            ("g4", "t3", timedelta(hours=2), "gpt-4o"),
        ]
        self.uuids = {label: _generation_uuid(index + 1) for index, (label, _, _, _) in enumerate(self.fixture)}
        bulk_create_ai_events(
            [
                {
                    "event": "$ai_generation",
                    "distinct_id": f"d-{trace_id}",
                    "team": self.team,
                    "timestamp": BASE + offset,
                    "event_uuid": self.uuids[label],
                    "properties": {
                        "$ai_trace_id": trace_id,
                        "$ai_session_id": f"s-{trace_id}",
                        "$ai_model": model,
                        "$ai_input": "hello there",
                        "$session_id": f"web-{trace_id}",
                    },
                }
                for label, trace_id, offset, model in self.fixture
            ]
        )

    def _create_generations(self, *specs: tuple[int, str, timedelta]) -> None:
        bulk_create_ai_events(
            [
                {
                    "event": "$ai_generation",
                    "distinct_id": f"d-{trace_id}",
                    "team": self.team,
                    "timestamp": BASE + offset,
                    "event_uuid": _generation_uuid(index),
                    "properties": {"$ai_trace_id": trace_id, "$ai_session_id": f"s-{trace_id}"},
                }
                for index, trace_id, offset in specs
            ]
        )

    def _walk(self, *, limit: int, **overrides: Any) -> list[Any]:
        walked: list[Any] = []
        cursor_timestamp: datetime | None = None
        cursor_unit_id = ""
        while True:
            page = self._fetch(
                cursor_timestamp=cursor_timestamp, cursor_unit_id=cursor_unit_id, limit=limit, **overrides
            )
            walked.extend(page.candidates)
            if page.exhausted:
                break
            cursor_timestamp, cursor_unit_id = page.next_cursor_timestamp, page.next_cursor_unit_id
        return walked

    def _count(self, **overrides: Any) -> int:
        kwargs: dict[str, Any] = {
            "team": self.team,
            "evaluation_id": str(self.evaluation.id),
            "target": "trace",
            "conditions": [],
            "window_start": WINDOW_START,
            "window_end": WINDOW_END,
            "rerun_existing": True,
        }
        kwargs.update(overrides)
        return count_backfill_candidates(**kwargs)

    def _fetch(self, **overrides: Any) -> Any:
        kwargs: dict[str, Any] = {
            "team": self.team,
            "evaluation_id": str(self.evaluation.id),
            "target": "generation",
            "conditions": [],
            "window_start": WINDOW_START,
            "window_end": WINDOW_END,
            "rerun_existing": True,
            "cursor_timestamp": None,
            "cursor_unit_id": "",
            "limit": 3,
        }
        kwargs.update(overrides)
        return fetch_backfill_candidates(**kwargs)

    @parameterized.expand([("generation", 4), ("trace", 3), ("session", 3)])
    def test_counts_every_unit_in_window_without_conditions(self, target: str, expected: int) -> None:
        assert self._count(target=target) == expected

    def test_window_bounds_exclude_units_outside_the_range(self) -> None:
        assert self._count(target="generation", window_end=BASE + timedelta(minutes=1)) == 1
        assert self._count(target="generation", window_start=BASE + timedelta(hours=1)) == 2

    def test_property_condition_filters_units_and_full_rollout_keeps_them_all(self) -> None:
        conditions = [
            {
                "properties": [{"key": "$ai_model", "value": "gpt-4o", "operator": "exact", "type": "event"}],
                "rollout_percentage": 100,
            }
        ]
        assert self._count(target="trace", conditions=conditions) == 2

    def test_zero_rollout_matches_nothing_and_condition_sets_are_ored(self) -> None:
        conditions = [
            {
                "properties": [{"key": "$ai_model", "value": "gpt-4o", "operator": "exact", "type": "event"}],
                "rollout_percentage": 0,
            },
            {
                "properties": [{"key": "$ai_model", "value": "gpt-4o-mini", "operator": "exact", "type": "event"}],
                "rollout_percentage": 100,
            },
        ]
        assert self._count(target="trace", conditions=conditions) == 1

    @parameterized.expand(
        [
            ("trace", "trace", "trace_id", "t1", 2),
            ("generation", "generation", "generation_uuid", _generation_uuid(1), 3),
            ("session", "session", "session_id", "s-t1", 2),
            # Verdicts emitted before $ai_target_type existed are generation verdicts.
            ("generation_without_target_type", "generation", None, _generation_uuid(1), 3),
        ]
    )
    def test_already_evaluated_units_are_excluded_unless_rerun(
        self, _case: str, target: str, target_type: str | None, target_id: str, expected: int
    ) -> None:
        properties: dict[str, Any] = {"$ai_evaluation_id": str(self.evaluation.id), "$ai_target_id": target_id}
        if target_type is not None:
            properties["$ai_target_type"] = target_type
        _create_event(
            team=self.team,
            event="$ai_evaluation",
            distinct_id="d",
            timestamp=BASE + timedelta(minutes=5),
            properties=properties,
        )
        flush_persons_and_events()
        assert self._count(target=target, rerun_existing=False) == expected
        assert self._count(target=target, rerun_existing=True) == expected + 1

    def test_a_verdict_landing_long_after_the_window_does_not_dedupe(self) -> None:
        _create_event(
            team=self.team,
            event="$ai_evaluation",
            distinct_id="d",
            timestamp=WINDOW_END + timedelta(days=3),
            properties={
                "$ai_evaluation_id": str(self.evaluation.id),
                "$ai_target_id": "t1",
                "$ai_target_type": "trace_id",
            },
        )
        flush_persons_and_events()
        assert self._count(target="trace", rerun_existing=False) == 3

    def test_pages_descend_by_timestamp_then_id_and_report_exhaustion(self) -> None:
        page1 = self._fetch(limit=3)
        assert [c.unit_id for c in page1.candidates] == [self.uuids["g4"], self.uuids["g3"], self.uuids["g2"]]
        assert page1.exhausted is False

        page2 = self._fetch(
            cursor_timestamp=page1.next_cursor_timestamp,
            cursor_unit_id=page1.next_cursor_unit_id,
            limit=3,
        )
        assert [c.unit_id for c in page2.candidates] == [self.uuids["g1"]]
        assert page2.exhausted is True

    def test_a_page_break_on_tied_timestamps_neither_drops_nor_repeats_a_unit(self) -> None:
        self._create_generations((6, "t5", timedelta(hours=1)))

        # limit=2 puts the break inside the pair sharing BASE + 1h, so paging depends on the
        # unit_id tiebreak rather than on the timestamp alone.
        walked = [candidate.unit_id for candidate in self._walk(limit=2)]

        tied = _generation_uuid(6)
        assert walked == [
            self.uuids["g4"],
            tied,
            self.uuids["g3"],
            self.uuids["g2"],
            self.uuids["g1"],
        ]
        assert len(set(walked)) == len(walked)

    def test_candidate_carries_the_fields_the_dispatcher_needs(self) -> None:
        page = self._fetch(target="trace", limit=1)
        candidate = page.candidates[0]
        assert candidate.unit_id == "t3"
        assert candidate.unit_timestamp == BASE + timedelta(hours=2)
        assert candidate.distinct_id == "d-t3"
        assert candidate.session_id == "web-t3"
        assert candidate.trace_id == "t3"

        generation = self._fetch(target="generation", limit=1).candidates[0]
        assert generation.unit_id == self.uuids["g4"]
        assert generation.trace_id == "t3"

    def test_candidate_without_a_web_session_reports_none(self) -> None:
        self._create_generations((5, "t4", timedelta(hours=3)))
        page = self._fetch(target="trace", limit=1)
        assert page.candidates[0].unit_id == "t4"
        assert page.candidates[0].session_id is None

    def test_a_condition_on_a_heavy_property_reads_the_native_ai_events_column(self) -> None:
        # `properties.$ai_input` is stripped from ai_events, so a filter that survives into the
        # SQL as a property read matches nothing on the real table.
        conditions = [
            {
                "properties": [{"key": "$ai_input", "value": "hello", "operator": "icontains", "type": "event"}],
                "rollout_percentage": 100,
            }
        ]
        executed: list[Any] = []

        def _capture(**kwargs: Any) -> Any:
            response = query_ai_events(**kwargs)
            executed.append(response)
            return response

        with patch(f"{CANDIDATES_MODULE}.query_ai_events", side_effect=_capture):
            self._count(target="generation", conditions=conditions)

        assert executed, "the count never reached ClickHouse"
        # The native column, not a JSONExtract on `properties`, which holds no heavy property.
        assert "ai_events.input" in (executed[0].clickhouse or "")

    def test_a_unit_spanning_the_cursor_is_returned_once_at_its_first_generation(self) -> None:
        self._create_generations((7, "t6", timedelta(minutes=30)), (8, "t6", timedelta(hours=3)))

        walked = [(candidate.unit_id, candidate.unit_timestamp) for candidate in self._walk(target="trace", limit=1)]

        # t6 spans the cursor: its later generation sits above every cursor the walk passes, and
        # the unit must still surface once, at the timestamp of its first generation.
        assert walked == [
            ("t3", BASE + timedelta(hours=2)),
            ("t2", BASE + timedelta(hours=1)),
            ("t6", BASE + timedelta(minutes=30)),
            ("t1", BASE),
        ]

    def test_empty_window_returns_no_candidates_and_a_zero_count(self) -> None:
        far_start = BASE + timedelta(days=30)
        far_end = far_start + timedelta(days=1)
        assert self._count(target="trace", window_start=far_start, window_end=far_end) == 0
        page = self._fetch(target="trace", window_start=far_start, window_end=far_end)
        assert page.candidates == []
        assert page.exhausted is True
