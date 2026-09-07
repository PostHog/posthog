import re
from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import BaseTest, ClickhouseTestMixin

from django.core.cache import cache

from parameterized import parameterized

from posthog.models.ai_events.test_util import bulk_create_ai_events
from posthog.models.team import Team

from products.ai_observability.backend.instrumentation_checklist.grading import VOLUME_FLOOR, ChecklistStats
from products.ai_observability.backend.instrumentation_checklist.stats import (
    _COUNTS_SQL,
    _TOOLS_DECLARED_SQL,
    WINDOW_DAYS,
    fetch_checklist_stats,
)

NOW = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)

_TOOL = {"type": "function", "function": {"name": "search"}}


def _ai_event(
    *,
    team: Team,
    event: str,
    trace_id: str,
    distinct_id: str | None = None,
    timestamp: datetime | None = None,
    properties: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "event": event,
        # An unset distinct_id mirrors the un-instrumented shape the user_identity check detects:
        # the SDK falls back to the trace id, so every trace looks like its own user.
        "distinct_id": distinct_id if distinct_id is not None else trace_id,
        "team": team,
        "timestamp": timestamp or NOW - timedelta(days=1),
        "properties": {"$ai_trace_id": trace_id, **(properties or {})},
    }


def _generations(team: Team, count: int) -> list[dict[str, Any]]:
    return [_ai_event(team=team, event="$ai_generation", trace_id=f"trace-{index}") for index in range(count)]


class TestFetchChecklistStats(ClickhouseTestMixin, BaseTest):
    def setUp(self) -> None:
        super().setUp()
        # Verdicts are cached per team, and the team id is stable across the class, so without this
        # the first test to run answers every later one.
        cache.clear()

    def test_counts_every_signal_the_checklist_grades(self) -> None:
        bulk_create_ai_events(
            [
                _ai_event(
                    team=self.team,
                    event="$ai_generation",
                    trace_id="trace-instrumented",
                    distinct_id="user-42",
                    properties={
                        "$ai_session_id": "session-1",
                        "$ai_tools_called": "search",
                        "$ai_tools": [{"type": "function", "function": {"name": "search"}}],
                        "$ai_parent_id": "span-root",
                    },
                ),
                _ai_event(team=self.team, event="$ai_generation", trace_id="trace-bare"),
                _ai_event(team=self.team, event="$ai_span", trace_id="trace-instrumented"),
                _ai_event(team=self.team, event="$ai_trace", trace_id="trace-instrumented"),
                _ai_event(team=self.team, event="$ai_embedding", trace_id="trace-bare"),
            ]
        )

        stats = fetch_checklist_stats(self.team)

        assert stats == ChecklistStats(
            generations=2,
            events_with_session=1,
            events_declining_session=0,
            generations_with_tool_calls=1,
            # Not False: nothing asked about definitions, because only the tool-calls warning reads
            # the answer and this project is nowhere near raising it.
            tools_declared=None,
            sdk_generations=2,
            sdk_generations_identified=1,
            spans=1,
            events_with_parent=1,
            # Neither generations + spans nor generations alone: $ai_trace and $ai_embedding count
            # too, or a trace-only project floors at zero and sits pending forever.
            total_events=5,
        )

    def test_a_project_with_no_ai_events_grades_at_zero_rather_than_raising(self) -> None:
        stats = fetch_checklist_stats(self.team)

        assert stats == ChecklistStats(
            generations=0,
            events_with_session=0,
            events_declining_session=0,
            generations_with_tool_calls=0,
            tools_declared=None,
            sdk_generations=0,
            sdk_generations_identified=0,
            spans=0,
            events_with_parent=0,
            total_events=0,
        )

    def test_another_teams_events_are_not_counted(self) -> None:
        other_team = Team.objects.create(organization=self.organization, name="other")
        bulk_create_ai_events(
            [
                _ai_event(team=self.team, event="$ai_generation", trace_id="ours"),
                _ai_event(
                    team=other_team,
                    event="$ai_generation",
                    trace_id="theirs",
                    distinct_id="user-42",
                    properties={"$ai_session_id": "session-x"},
                ),
            ]
        )

        stats = fetch_checklist_stats(self.team)

        assert stats.total_events == 1
        assert stats.generations == 1
        assert stats.events_with_session == 0
        assert stats.sdk_generations_identified == 0

    def test_events_older_than_the_window_are_excluded(self) -> None:
        bulk_create_ai_events(
            [
                _ai_event(
                    team=self.team,
                    event="$ai_generation",
                    trace_id="recent",
                    timestamp=datetime.now(UTC) - timedelta(days=WINDOW_DAYS - 1),
                ),
                _ai_event(
                    team=self.team,
                    event="$ai_generation",
                    trace_id="aged-out",
                    timestamp=datetime.now(UTC) - timedelta(days=WINDOW_DAYS + 1),
                ),
            ]
        )

        stats = fetch_checklist_stats(self.team)

        assert stats.total_events == 1
        assert stats.generations == 1

    def test_tool_definitions_are_read_from_the_native_column(self) -> None:
        # The ai_events MV strips $ai_tools from the properties blob, so a properties read returns a
        # silent zero in production and the checklist accuses a correctly instrumented project.
        # bulk_create_ai_events does not strip it, so no seeded-data assertion can catch this.
        normalized = " ".join(_TOOLS_DECLARED_SQL.split())
        assert "coalesce(tools, '')" in normalized
        # \b keeps $ai_tools_called, which does live in the properties blob, out of the match.
        assert re.search(r"properties\.\$ai_tools\b", normalized) is None

    def test_the_tools_column_stays_out_of_the_counts_query(self) -> None:
        # It is the widest column in the table, and reading it for every row costs about as much as
        # every other column the checklist touches put together.
        # \b keeps $ai_tools_called, which lives in the properties blob, out of the match.
        assert re.search(r"\btools\b", " ".join(_COUNTS_SQL.split())) is None

    @parameterized.expand(
        [
            ("an_empty_array_is_not_a_declaration", [], None, False),
            ("a_real_definition_is", [_TOOL], None, True),
            # The read behind this is the widest in the checklist, and its answer only picks between
            # two warning sentences. A project already recording calls never raises that warning.
            ("a_recorded_call_leaves_the_question_unasked", [_TOOL], "search", None),
        ]
    )
    def test_declared_tool_definitions(
        self, _name: str, tools: list[dict[str, Any]], tools_called: str | None, expected: bool | None
    ) -> None:
        properties: dict[str, Any] = {"$ai_tools": tools}
        if tools_called is not None:
            properties["$ai_tools_called"] = tools_called
        bulk_create_ai_events(
            [
                _ai_event(team=self.team, event="$ai_generation", trace_id=f"trace-{index}", properties=properties)
                for index in range(VOLUME_FLOOR)
            ]
        )

        assert fetch_checklist_stats(self.team).tools_declared is expected

    def test_a_session_id_counts_when_it_arrives_on_a_trace_rather_than_a_generation(self) -> None:
        bulk_create_ai_events(
            [
                _ai_event(
                    team=self.team,
                    event="$ai_trace",
                    trace_id="trace-1",
                    properties={"$ai_session_id": "session-1"},
                ),
                _ai_event(team=self.team, event="$ai_generation", trace_id="trace-1"),
            ]
        )

        assert fetch_checklist_stats(self.team).events_with_session == 1

    def test_only_an_explicit_null_session_id_reads_as_declining_a_session(self) -> None:
        # The native session_id column is null for all four of these, so the opt-out can only be
        # read off the raw properties blob. An empty string is usually an unset variable rather
        # than a decision, and counting it would silence the check for a project with a bug.
        bulk_create_ai_events(
            [
                _ai_event(
                    team=self.team, event="$ai_generation", trace_id="trace-null", properties={"$ai_session_id": None}
                ),
                _ai_event(team=self.team, event="$ai_generation", trace_id="trace-absent"),
                _ai_event(
                    team=self.team, event="$ai_generation", trace_id="trace-empty", properties={"$ai_session_id": ""}
                ),
                _ai_event(
                    team=self.team, event="$ai_generation", trace_id="trace-real", properties={"$ai_session_id": "s1"}
                ),
            ]
        )

        stats = fetch_checklist_stats(self.team)
        assert (stats.events_declining_session, stats.events_with_session) == (1, 1)

    def test_otel_ingested_generations_are_left_out_of_the_identity_counts(self) -> None:
        bulk_create_ai_events(
            [
                _ai_event(team=self.team, event="$ai_generation", trace_id="trace-sdk"),
                _ai_event(
                    team=self.team,
                    event="$ai_generation",
                    trace_id="trace-otel",
                    # An unidentified OTel span carries one random UUID per OTLP request, which never
                    # equals the hex trace id, so it reads as identified to the distinct_id heuristic.
                    distinct_id="4d1cc9d4-0f2e-4a55-9a9b-6c0f7d3e1b22",
                    properties={"$ai_ingestion_source": "otel"},
                ),
            ]
        )

        stats = fetch_checklist_stats(self.team)

        assert stats.generations == 2
        assert stats.sdk_generations == 1
        assert stats.sdk_generations_identified == 0

    def test_a_verdict_is_reused_until_a_refresh_asks_for_a_new_one(self) -> None:
        bulk_create_ai_events(_generations(self.team, VOLUME_FLOOR))
        assert fetch_checklist_stats(self.team).total_events == VOLUME_FLOOR

        bulk_create_ai_events([_ai_event(team=self.team, event="$ai_span", trace_id="trace-extra")])

        assert fetch_checklist_stats(self.team).total_events == VOLUME_FLOOR
        assert fetch_checklist_stats(self.team, force_refresh=True).total_events == VOLUME_FLOOR + 1

    def test_a_project_below_the_volume_floor_is_never_held_at_its_first_counts(self) -> None:
        # Every check grades pending down here, which is the card someone watches while their first
        # events land. A cached verdict would answer them with the counts from before they started.
        assert fetch_checklist_stats(self.team).total_events == 0

        bulk_create_ai_events(_generations(self.team, VOLUME_FLOOR - 1))

        assert fetch_checklist_stats(self.team).total_events == VOLUME_FLOOR - 1

    @parameterized.expand([("counts", _COUNTS_SQL), ("tools_declared", _TOOLS_DECLARED_SQL)])
    def test_every_aggregate_stays_ungrouped(self, _name: str, sql: str) -> None:
        # An ungrouped aggregate always returns exactly one row, so query_ai_events' empty-result
        # probe never fires and the stripped events table stays unreachable. A GROUP BY, a HAVING,
        # or dropping the outer count() would let a project with no matching row raise
        # AIEventsNotFoundError instead of grading.
        normalized = " ".join(sql.split()).upper()
        assert "COUNT()" in normalized
        assert "GROUP BY" not in normalized
        assert "HAVING" not in normalized
