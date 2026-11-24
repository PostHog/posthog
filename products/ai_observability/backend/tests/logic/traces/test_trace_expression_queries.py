import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from posthog.test.base import BaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.query import execute_hogql_query

from posthog.hogql_queries.ai.ai_column_rewriter import EVENTS_FALLBACK_PROPERTY_TYPE_OVERRIDES
from posthog.models.ai_events.test_util import bulk_create_ai_events
from posthog.models.event.util import bulk_create_events

from products.ai_observability.backend.logic.traces.trace_expression_queries import (
    AI_EVENTS_COLUMNS,
    EVENTS_COLUMNS,
    TraceColumns,
    event_identified,
    grouped,
    over_trace,
    trace_cost,
    trace_errored,
    trace_latency,
    trace_person_id,
    trace_session_id,
)

CASES_PATH = Path(__file__).parents[4] / "shared" / "trace_expression_cases.json"
T0 = datetime(2026, 9, 1, 10, 0, 0, tzinfo=UTC)
TRACE_ID = "trace-a"

CASES: list[dict[str, Any]] = json.loads(CASES_PATH.read_text())
LAYOUTS = {"ai_events": ("posthog.ai_events", AI_EVENTS_COLUMNS), "events": ("events", EVENTS_COLUMNS)}


def case_on_each_layout() -> list[tuple[str, dict[str, Any], str]]:
    return [(f"{case['name']}_{layout}", case, layout) for case in CASES for layout in LAYOUTS]


def person_id_of(distinct_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, distinct_id))


def expected_person(case: dict[str, Any], layout: str) -> str | None:
    if case["person"] is None or layout == "ai_events":
        return case["person"]
    return person_id_of(case["person"])


def seed(team: Any, events: list[dict[str, Any]]) -> None:
    rows = []
    for index, event in enumerate(events):
        properties: dict[str, Any] = {"$ai_trace_id": TRACE_ID}
        for key, property_name in (
            ("latency", "$ai_latency"),
            ("parent_id", "$ai_parent_id"),
            ("is_error", "$ai_is_error"),
            ("error", "$ai_error"),
            ("ingestion_source", "$ai_ingestion_source"),
            ("total_cost", "$ai_total_cost_usd"),
            ("session_id", "$ai_session_id"),
        ):
            if event.get(key) is not None:
                properties[property_name] = event[key]
        distinct_id = event.get("distinct_id", "user-1")
        rows.append(
            {
                "event": event["event"],
                "event_uuid": f"00000000-0000-4000-8000-{index:012d}",
                "distinct_id": distinct_id,
                "person_id": person_id_of(distinct_id),
                "team": team,
                "timestamp": T0 + timedelta(seconds=event.get("second", index)),
                "properties": properties,
            }
        )
    bulk_create_events(rows)
    bulk_create_ai_events(rows)


class TestTraceExpressionQueries(ClickhouseTestMixin, BaseTest):
    def _run(self, select: list[ast.Expr], layout: str, **query_parts: Any) -> list[tuple[Any, ...]]:
        table_chain: list[str | int] = list(LAYOUTS[layout][0].split("."))
        query = ast.SelectQuery(
            select=select,
            select_from=ast.JoinExpr(table=ast.Field(chain=table_chain)),
            **query_parts,
        )
        response = execute_hogql_query(
            query=query,
            team=self.team,
            context=HogQLContext(team_id=self.team.pk, property_type_overrides=EVENTS_FALLBACK_PROPERTY_TYPE_OVERRIDES),
        )
        return [tuple(row) for row in response.results]

    def _grouped(self, layout: str, build: Any) -> list[tuple[Any, ...]]:
        columns: TraceColumns = LAYOUTS[layout][1]
        return self._run([build(columns, grouped)], layout, group_by=[columns.trace_id])

    def _windowed(self, layout: str, build: Any) -> list[tuple[Any, ...]]:
        columns: TraceColumns = LAYOUTS[layout][1]
        return self._run([build(columns, over_trace(columns.trace_id))], layout)

    @parameterized.expand(case_on_each_layout())
    def test_trace_latency_cases(self, _name: str, case: dict[str, Any], layout: str) -> None:
        seed(self.team, case["events"])

        assert self._grouped(layout, trace_latency) == [(case["latency"],)]

    @parameterized.expand(case_on_each_layout())
    def test_trace_latency_window_matches_grouped(self, _name: str, case: dict[str, Any], layout: str) -> None:
        seed(self.team, case["events"])

        assert self._windowed(layout, trace_latency) == [(case["latency"],)] * len(case["events"])

    @parameterized.expand(case_on_each_layout())
    def test_trace_errored_cases(self, _name: str, case: dict[str, Any], layout: str) -> None:
        seed(self.team, case["events"])

        assert self._grouped(layout, trace_errored) == [(case["errored"],)]
        assert self._windowed(layout, trace_errored) == [(case["errored"],)] * len(case["events"])

    @parameterized.expand(case_on_each_layout())
    def test_event_identified_cases(self, _name: str, case: dict[str, Any], layout: str) -> None:
        seed(self.team, case["events"])
        columns: TraceColumns = LAYOUTS[layout][1]

        rows = self._run(
            [ast.Field(chain=["timestamp"]), event_identified(columns)],
            layout,
            order_by=[ast.OrderExpr(expr=ast.Field(chain=["timestamp"]), order="ASC")],
        )

        assert [bool(identified) for _, identified in rows] == case["identified"]

    @parameterized.expand(case_on_each_layout())
    def test_trace_cost_cases(self, _name: str, case: dict[str, Any], layout: str) -> None:
        seed(self.team, case["events"])

        assert self._grouped(layout, trace_cost) == [(case["cost"],)]
        assert self._windowed(layout, trace_cost) == [(case["cost"],)] * len(case["events"])

    @parameterized.expand(case_on_each_layout())
    def test_trace_person_id_cases(self, _name: str, case: dict[str, Any], layout: str) -> None:
        seed(self.team, case["events"])
        expected = expected_person(case, layout)

        persons = [person for (person,) in self._grouped(layout, trace_person_id)]
        windowed = [person for (person,) in self._windowed(layout, trace_person_id)]

        assert [str(person) if person is not None else None for person in persons] == [expected]
        assert {str(person) if person is not None else None for person in windowed} == {expected}

    @parameterized.expand(case_on_each_layout())
    def test_trace_session_id_cases(self, _name: str, case: dict[str, Any], layout: str) -> None:
        seed(self.team, case["events"])

        assert self._grouped(layout, trace_session_id) == [(case["session"],)]
        assert self._windowed(layout, trace_session_id) == [(case["session"],)] * len(case["events"])
