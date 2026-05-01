"""Strip-migration unit tests for sentiment Temporal data layer.

`fetch_generations` and `fetch_generations_by_uuid` both moved from
`FROM events SELECT properties.$ai_input` to `FROM posthog.ai_events SELECT input`
behind the resolver. Both must continue to read populated `ai_input` for
post-strip events (the resolver wires that up); these tests assert the contract
without hitting ClickHouse.
"""

from typing import cast

import pytest
from unittest.mock import MagicMock, patch

from posthog.hogql import ast

from posthog.temporal.llm_analytics.sentiment.data import fetch_generations, fetch_generations_by_uuid


@pytest.fixture
def team(db):
    from posthog.models.organization import Organization
    from posthog.models.team import Team

    organization = Organization.objects.create(name="Test Org")
    return Team.objects.create(organization=organization, name="Test Team")


def _resolver_response(rows: list[list]) -> MagicMock:
    response = MagicMock()
    response.results = rows
    return response


@pytest.mark.django_db
class TestFetchGenerations:
    def test_groups_rows_by_trace_id(self, team):
        # Each row tuple: (uuid, ai_input, trace_id) — order matches GENERATIONS_QUERY's outer SELECT.
        with patch("posthog.hogql_queries.ai.ai_table_resolver.execute_with_ai_events_fallback") as mock_resolver:
            mock_resolver.return_value = _resolver_response(
                [
                    ["uuid-1", '[{"role":"user","content":"hi A"}]', "trace-A"],
                    ["uuid-2", '[{"role":"user","content":"hi B"}]', "trace-B"],
                    ["uuid-3", '[{"role":"user","content":"hi A again"}]', "trace-A"],
                ]
            )

            result = fetch_generations(
                team_id=team.id,
                trace_ids=["trace-A", "trace-B"],
                date_from="2026-04-27 07:00:00",
                date_to="2026-04-27 08:00:00",
            )

            assert set(result.rows_by_trace.keys()) == {"trace-A", "trace-B"}
            assert len(result.rows_by_trace["trace-A"]) == 2
            assert len(result.rows_by_trace["trace-B"]) == 1
            # Bytes accumulator counts the raw JSON strings sent over the wire.
            assert result.total_input_bytes > 0

    def test_skips_rows_with_unparseable_input(self, team):
        with patch("posthog.hogql_queries.ai.ai_table_resolver.execute_with_ai_events_fallback") as mock_resolver:
            mock_resolver.return_value = _resolver_response(
                [
                    ["uuid-1", "{not-json", "trace-A"],
                    ["uuid-2", '[{"role":"user","content":"valid"}]', "trace-A"],
                ]
            )
            result = fetch_generations(
                team_id=team.id,
                trace_ids=["trace-A"],
                date_from="2026-04-27 07:00:00",
                date_to="2026-04-27 08:00:00",
            )
            # Only the valid row survives; invalid JSON drops silently.
            assert len(result.rows_by_trace["trace-A"]) == 1

    def test_query_reads_native_input_from_ai_events(self, team):
        """If someone reverts the GENERATIONS_QUERY template to
        `properties.$ai_input`, this test catches it."""
        with patch("posthog.hogql_queries.ai.ai_table_resolver.execute_with_ai_events_fallback") as mock_resolver:
            mock_resolver.return_value = _resolver_response([])
            fetch_generations(
                team_id=team.id,
                trace_ids=["trace-A"],
                date_from="2026-04-27 07:00:00",
                date_to="2026-04-27 08:00:00",
            )

            kwargs = mock_resolver.call_args.kwargs
            outer = cast(ast.SelectQuery, kwargs["query"])
            inner = outer.select_from.table  # type: ignore[union-attr]
            assert isinstance(inner, ast.SelectQuery)
            from_chain = inner.select_from.table.chain  # type: ignore[union-attr]
            # nosemgrep: hogql-no-string-table-chain
            assert from_chain == ["posthog", "ai_events"]


_TRACE_RESOLVE_PATH = "posthog.hogql_queries.ai.trace_id_resolver.resolve_trace_ids_for_generation_uuids"


@pytest.mark.django_db
class TestFetchGenerationsByUuid:
    @patch(_TRACE_RESOLVE_PATH, return_value={"uuid-1": "trace-A", "uuid-2": "trace-B"})
    def test_returns_flat_list(self, _mock_resolve, team):
        with patch("posthog.hogql_queries.ai.ai_table_resolver.execute_with_ai_events_fallback") as mock_resolver:
            mock_resolver.return_value = _resolver_response(
                [
                    ["uuid-1", '[{"role":"user","content":"hi"}]'],
                    ["uuid-2", '[{"role":"user","content":"there"}]'],
                ]
            )
            rows, total_bytes = fetch_generations_by_uuid(
                team_id=team.id,
                generation_ids=["uuid-1", "uuid-2"],
                date_from="2026-04-27 07:00:00",
                date_to="2026-04-27 08:00:00",
            )
            assert len(rows) == 2
            assert total_bytes > 0

    @patch(_TRACE_RESOLVE_PATH, return_value={"uuid-good": "trace-A", "uuid-bad": "trace-A"})
    def test_skips_unparseable_input(self, _mock_resolve, team):
        with patch("posthog.hogql_queries.ai.ai_table_resolver.execute_with_ai_events_fallback") as mock_resolver:
            mock_resolver.return_value = _resolver_response(
                [
                    ["uuid-bad", "not-json"],
                    ["uuid-good", '[{"role":"user","content":"hi"}]'],
                ]
            )
            rows, _ = fetch_generations_by_uuid(
                team_id=team.id,
                generation_ids=["uuid-bad", "uuid-good"],
                date_from="2026-04-27 07:00:00",
                date_to="2026-04-27 08:00:00",
            )
            assert len(rows) == 1
            assert rows[0][0] == "uuid-good"

    @patch(_TRACE_RESOLVE_PATH, return_value={})
    def test_no_trace_ids_resolved_skips_heavy_fetch(self, _mock_resolve, team):
        """When the events preflight returns no trace_ids — uuids purged or
        outside the window — skip the heavy ai_events fan-out entirely."""
        with patch("posthog.hogql_queries.ai.ai_table_resolver.execute_with_ai_events_fallback") as mock_resolver:
            rows, total_bytes = fetch_generations_by_uuid(
                team_id=team.id,
                generation_ids=["uuid-1", "uuid-2"],
                date_from="2026-04-27 07:00:00",
                date_to="2026-04-27 08:00:00",
            )
            assert rows == []
            assert total_bytes == 0
            assert mock_resolver.call_count == 0

    @patch(_TRACE_RESOLVE_PATH, return_value={"uuid-1": "trace-A", "uuid-2": "trace-B"})
    def test_trace_ids_flow_into_heavy_query(self, _mock_resolve, team):
        """The discovered trace_ids must land in the WHERE so the heavy fetch
        hits the ai_events `(team_id, trace_id, timestamp)` sorting-key
        prefix and single-shard via the cityHash64 sharding key."""
        with patch("posthog.hogql_queries.ai.ai_table_resolver.execute_with_ai_events_fallback") as mock_resolver:
            mock_resolver.return_value = _resolver_response([])
            fetch_generations_by_uuid(
                team_id=team.id,
                generation_ids=["uuid-1", "uuid-2"],
                date_from="2026-04-27 07:00:00",
                date_to="2026-04-27 08:00:00",
            )
            placeholders = mock_resolver.call_args.kwargs["placeholders"]
            assert "trace_ids" in placeholders
            values = sorted(c.value for c in placeholders["trace_ids"].exprs)
            assert values == ["trace-A", "trace-B"]
