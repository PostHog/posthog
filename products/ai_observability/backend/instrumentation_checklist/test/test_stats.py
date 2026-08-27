import re
from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import BaseTest, ClickhouseTestMixin

from posthog.models.ai_events.test_util import bulk_create_ai_events
from posthog.models.team import Team

from products.ai_observability.backend.instrumentation_checklist.grading import ChecklistStats
from products.ai_observability.backend.instrumentation_checklist.stats import (
    _STATS_SQL,
    WINDOW_DAYS,
    fetch_checklist_stats,
)

NOW = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)


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


class TestFetchChecklistStats(ClickhouseTestMixin, BaseTest):
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
            generations_with_tools_declared=1,
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
            generations_with_tools_declared=0,
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
        normalized = " ".join(_STATS_SQL.split())
        assert "coalesce(tools, '')" in normalized
        # \b keeps $ai_tools_called, which does live in the properties blob, out of the match.
        assert re.search(r"properties\.\$ai_tools\b", normalized) is None

    def test_an_empty_tool_array_is_not_counted_as_declared_definitions(self) -> None:
        bulk_create_ai_events(
            [
                _ai_event(
                    team=self.team,
                    event="$ai_generation",
                    trace_id="trace-empty-tools",
                    properties={"$ai_tools": []},
                ),
                _ai_event(
                    team=self.team,
                    event="$ai_generation",
                    trace_id="trace-real-tools",
                    properties={"$ai_tools": [{"type": "function", "function": {"name": "search"}}]},
                ),
            ]
        )

        assert fetch_checklist_stats(self.team).generations_with_tools_declared == 1

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

    def test_the_aggregate_stays_ungrouped(self) -> None:
        # An ungrouped aggregate always returns exactly one row, so query_ai_events' empty-result
        # probe never fires and the stripped events table stays unreachable. A GROUP BY or HAVING
        # would let an empty project raise AIEventsNotFoundError instead of grading at zero.
        normalized = " ".join(_STATS_SQL.split()).upper()
        assert "GROUP BY" not in normalized
        assert "HAVING" not in normalized
