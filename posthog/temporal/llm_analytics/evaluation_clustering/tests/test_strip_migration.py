"""Strip-migration tests for the eval clustering data layer.

`fetch_generation_contents` is the only at-risk reader in
`evaluation_clustering/data.py` (it reads heavy `input` /
`output_choices`). It now routes through `execute_with_ai_events_fallback`
so the labeling agent's `get_generation_details` tool sees populated
content for post-strip rows.
"""

from typing import cast

import pytest
from unittest.mock import MagicMock, patch

from posthog.hogql import ast

from posthog.temporal.llm_analytics.evaluation_clustering.data import fetch_generation_contents


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
        # No resolver call at all when there's nothing to fetch — guards against
        # an N×0 query that would scan the whole window.
        with patch(
            "posthog.temporal.llm_analytics.evaluation_clustering.data.execute_with_ai_events_fallback"
        ) as mock_resolver:
            result = fetch_generation_contents(team, generation_ids=[])
            assert result == {}
            assert mock_resolver.call_count == 0

    def test_returns_per_generation_dict(self, team):
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
            result = fetch_generation_contents(team, generation_ids=["gid-1", "gid-2"])
            assert set(result.keys()) == {"gid-1", "gid-2"}
            assert result["gid-1"]["model"] == "gpt-4o"
            assert "hi" in result["gid-1"]["input"]
            assert "hello" in result["gid-1"]["output"]

    def test_truncates_input_and_output(self, team):
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
            )
            # `_truncate` returns `s[:limit] + "… [N more chars]"` so the prefix
            # length is `limit` and the total length is `limit + suffix_len`.
            assert result["gid-1"]["input"].startswith("x" * 100)
            assert "more chars]" in result["gid-1"]["input"]
            assert result["gid-1"]["output"].startswith("x" * 200)
            assert "more chars]" in result["gid-1"]["output"]

    def test_query_reads_native_heavy_columns_from_ai_events(self, team):
        """The whole point of the migration is that `input` / `output_choices`
        come off the dedicated `ai_events` columns rather than NULL JSON-extracts
        on `events.properties`. Lock the SQL shape."""
        from datetime import UTC, datetime

        with patch(
            "posthog.temporal.llm_analytics.evaluation_clustering.data.execute_with_ai_events_fallback"
        ) as mock_resolver:
            mock_resolver.return_value = _resolver_response([])
            fetch_generation_contents(
                team,
                generation_ids=["gid-1"],
                window_start=datetime(2026, 4, 27, 7, 0, 0, tzinfo=UTC),
                window_end=datetime(2026, 4, 27, 8, 0, 0, tzinfo=UTC),
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
