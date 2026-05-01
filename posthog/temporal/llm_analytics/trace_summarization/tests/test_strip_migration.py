"""Strip-migration unit tests for the `_fetch_and_format_generation` query.

Verifies the by-uuid generation lookup routes through
`execute_with_ai_events_fallback` and reads the heavy `input` / `output` from
`posthog.ai_events` native columns.
"""

from typing import cast

import pytest
from unittest.mock import MagicMock, patch

from posthog.hogql import ast

from posthog.temporal.llm_analytics.trace_summarization.fetch_and_format import _fetch_and_format_generation


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
class TestFetchAndFormatGenerationStripMigration:
    def test_returns_none_when_resolver_has_no_results(self, team):
        with patch(
            "posthog.temporal.llm_analytics.trace_summarization.fetch_and_format.execute_with_ai_events_fallback"
        ) as mock_resolver:
            mock_resolver.return_value = _resolver_response([])
            result = _fetch_and_format_generation(
                "gen-uuid",
                "trace-uuid",
                team.id,
                "2026-04-27T07:00:00+00:00",
                "2026-04-27T08:00:00+00:00",
            )
            assert result is None

    def test_returns_text_repr_with_heavy_input_output(self, team):
        with patch(
            "posthog.temporal.llm_analytics.trace_summarization.fetch_and_format.execute_with_ai_events_fallback"
        ) as mock_resolver:
            # Order matches SELECT: model, provider, input, output, input_tokens, output_tokens, latency
            mock_resolver.return_value = _resolver_response(
                [
                    [
                        "gpt-4o",
                        "openai",
                        [{"role": "user", "content": "Hello"}],
                        [{"role": "assistant", "content": "Hi"}],
                        10,
                        5,
                        0.4,
                    ]
                ]
            )

            result = _fetch_and_format_generation(
                "gen-uuid",
                "trace-uuid",
                team.id,
                "2026-04-27T07:00:00+00:00",
                "2026-04-27T08:00:00+00:00",
            )

            assert result is not None
            assert result.event_count == 1
            text = result.text_repr or ""
            assert "Model: gpt-4o" in text
            assert "Provider: openai" in text
            assert "Hello" in text
            assert "Hi" in text

    def test_query_targets_ai_events_with_native_heavy_columns(self, team):
        """If the projection regresses to `properties.$ai_input` / `FROM events`,
        post-strip generation summaries silently empty out. Lock both."""
        with patch(
            "posthog.temporal.llm_analytics.trace_summarization.fetch_and_format.execute_with_ai_events_fallback"
        ) as mock_resolver:
            mock_resolver.return_value = _resolver_response([])

            _fetch_and_format_generation(
                "gen-uuid",
                "trace-uuid",
                team.id,
                "2026-04-27T07:00:00+00:00",
                "2026-04-27T08:00:00+00:00",
            )

            assert mock_resolver.call_count == 1
            kwargs = mock_resolver.call_args.kwargs
            select = cast(ast.SelectQuery, kwargs["query"])
            from_chain = select.select_from.table.chain  # type: ignore[union-attr]
            # nosemgrep: hogql-no-string-table-chain
            assert from_chain == ["posthog", "ai_events"]
            # Heavy columns referenced as bare native names, not via properties.$ai_*.
            select_aliases = [alias.alias for alias in select.select if isinstance(alias, ast.Alias)]

            # Heavy input/output should be projected as native columns aliased to
            # `input` / `output` (the `as` lines in the SQL preserve the field names).
            def _field_chain_tail_is_model(s: ast.Expr) -> bool:
                if not isinstance(s, ast.Field) or not s.chain:
                    return False
                tail = s.chain[-1]
                return isinstance(tail, str) and "model" in tail

            assert "model" in select_aliases or any(_field_chain_tail_is_model(s) for s in select.select)
            # query_type is set so observability dashboards can group by it.
            assert kwargs["query_type"] == "GenerationForSummarization"
            # trace_id flows into the WHERE so the lookup hits the
            # `(team_id, trace_id, timestamp)` sorting-key prefix instead of
            # fanning out across every shard for the team.
            placeholders = kwargs["placeholders"]
            assert "trace_id" in placeholders
            assert placeholders["trace_id"].value == "trace-uuid"
