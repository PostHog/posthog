"""Strip-migration tests for the eval clustering data layer.

`fetch_generation_contents` is the only at-risk reader in
`evaluation_clustering/data.py` (it reads heavy `input` / `output_choices`).
It uses a two-query pattern: resolves uuid → trace_id off `events`
first, then runs the heavy fetch on `ai_events` with `trace_id IN (...)`
so the lookup hits the sorting-key prefix `(team_id, trace_id, timestamp)`
and lands on a single shard via the cityHash64 sharding key. Tests mock
both layers.
"""

from datetime import UTC, datetime
from typing import cast

import pytest
from unittest.mock import MagicMock, patch

from posthog.hogql import ast

from posthog.temporal.llm_analytics.evaluation_clustering.data import fetch_generation_contents

_RESOLVE_PATH = "posthog.temporal.llm_analytics.evaluation_clustering.data.resolve_trace_ids_for_generation_uuids"
_WINDOW_START = datetime(2026, 4, 27, 7, 0, 0, tzinfo=UTC)
_WINDOW_END = datetime(2026, 4, 27, 8, 0, 0, tzinfo=UTC)


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
class TestFetchGenerationContents:
    def test_empty_id_list_short_circuits(self, team):
        # No queries at all when there's nothing to fetch — guards against
        # an N×0 query that would scan the whole window.
        with (
            patch(
                "posthog.temporal.llm_analytics.evaluation_clustering.data.execute_with_ai_events_fallback"
            ) as mock_resolver,
            patch(_RESOLVE_PATH) as mock_resolve,
        ):
            result = fetch_generation_contents(
                team, generation_ids=[], window_start=_WINDOW_START, window_end=_WINDOW_END
            )
            assert result == {}
            assert mock_resolver.call_count == 0
            assert mock_resolve.call_count == 0

    @patch(_RESOLVE_PATH, return_value={"gid-1": "trace-A", "gid-2": "trace-B"})
    def test_returns_per_generation_dict(self, _mock_resolve, team):
        with patch(
            "posthog.temporal.llm_analytics.evaluation_clustering.data.execute_with_ai_events_fallback"
        ) as mock_resolver:
            # Row tuple: (generation_id, model, input_raw, output_raw)
            mock_resolver.return_value = _resolver_response(
                [
                    ["gid-1", "gpt-4o", '[{"role":"user","content":"hi"}]', '[{"role":"assistant","content":"hello"}]'],
                    ["gid-2", "gpt-4o", '[{"role":"user","content":"yo"}]', '[{"role":"assistant","content":"sup"}]'],
                ]
            )
            result = fetch_generation_contents(
                team, generation_ids=["gid-1", "gid-2"], window_start=_WINDOW_START, window_end=_WINDOW_END
            )
            assert set(result.keys()) == {"gid-1", "gid-2"}
            assert result["gid-1"]["model"] == "gpt-4o"
            assert "hi" in result["gid-1"]["input"]
            assert "hello" in result["gid-1"]["output"]

    @patch(_RESOLVE_PATH, return_value={"gid-1": "trace-A"})
    def test_truncates_input_and_output(self, _mock_resolve, team):
        big = "x" * 5000
        with patch(
            "posthog.temporal.llm_analytics.evaluation_clustering.data.execute_with_ai_events_fallback"
        ) as mock_resolver:
            mock_resolver.return_value = _resolver_response([["gid-1", "gpt-4o", big, big]])
            result = fetch_generation_contents(
                team,
                generation_ids=["gid-1"],
                max_input_chars=100,
                max_output_chars=200,
                window_start=_WINDOW_START,
                window_end=_WINDOW_END,
            )
            # `_truncate` returns `s[:limit] + "… [N more chars]"` so the prefix
            # length is `limit` and the total length is `limit + suffix_len`.
            assert result["gid-1"]["input"].startswith("x" * 100)
            assert "more chars]" in result["gid-1"]["input"]
            assert result["gid-1"]["output"].startswith("x" * 200)
            assert "more chars]" in result["gid-1"]["output"]

    @patch(_RESOLVE_PATH, return_value={"gid-1": "trace-A"})
    def test_query_reads_native_heavy_columns_from_ai_events(self, _mock_resolve, team):
        """The whole point of the migration is that `input` / `output_choices`
        come off the dedicated `ai_events` columns rather than NULL JSON-extracts
        on `events.properties`. Lock the SQL shape."""
        with patch(
            "posthog.temporal.llm_analytics.evaluation_clustering.data.execute_with_ai_events_fallback"
        ) as mock_resolver:
            mock_resolver.return_value = _resolver_response([])
            fetch_generation_contents(
                team, generation_ids=["gid-1"], window_start=_WINDOW_START, window_end=_WINDOW_END
            )

            kwargs = mock_resolver.call_args.kwargs
            select = cast(ast.SelectQuery, kwargs["query"])
            from_chain = select.select_from.table.chain  # type: ignore[union-attr]
            # nosemgrep: hogql-no-string-table-chain
            assert from_chain == ["posthog", "ai_events"]
            # Settings forwarded so the resolver runs with the 120s clustering
            # timeout. Lock the actual value so a future "tightening" of the
            # default doesn't silently break clustering on long traces.
            from posthog.temporal.llm_analytics.evaluation_clustering.data import CLUSTERING_QUERY_MAX_EXECUTION_TIME

            assert kwargs["settings"] is not None
            assert kwargs["settings"].max_execution_time == CLUSTERING_QUERY_MAX_EXECUTION_TIME
            assert kwargs["query_type"] == "GenerationContentsForLabeling"

    @patch(_RESOLVE_PATH, return_value={"gid-1": "trace-A", "gid-2": "trace-B"})
    def test_trace_ids_flow_into_heavy_query(self, _mock_resolve, team):
        """The discovered trace_ids must land in the WHERE so the heavy fetch
        gets the full ai_events sorting-key prefix + cityHash64 sharding-key
        single-shard pruning."""
        with patch(
            "posthog.temporal.llm_analytics.evaluation_clustering.data.execute_with_ai_events_fallback"
        ) as mock_resolver:
            mock_resolver.return_value = _resolver_response([])
            fetch_generation_contents(
                team, generation_ids=["gid-1", "gid-2"], window_start=_WINDOW_START, window_end=_WINDOW_END
            )

            placeholders = mock_resolver.call_args.kwargs["placeholders"]
            assert "trace_ids" in placeholders
            values = sorted(c.value for c in placeholders["trace_ids"].exprs)
            assert values == ["trace-A", "trace-B"]

    @patch(_RESOLVE_PATH, return_value={})
    def test_no_trace_ids_resolved_skips_heavy_fetch(self, _mock_resolve, team):
        """When the events preflight returns nothing — uuids purged or outside
        the window — skip the heavy fan-out entirely."""
        with patch(
            "posthog.temporal.llm_analytics.evaluation_clustering.data.execute_with_ai_events_fallback"
        ) as mock_resolver:
            result = fetch_generation_contents(
                team, generation_ids=["gid-1"], window_start=_WINDOW_START, window_end=_WINDOW_END
            )
            assert result == {}
            assert mock_resolver.call_count == 0
