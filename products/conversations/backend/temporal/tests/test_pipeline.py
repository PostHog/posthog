from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from parameterized import parameterized

from products.conversations.backend.temporal.pipeline import (
    MAX_ATTEMPTS,
    BuildContextOutput,
    DraftOutput,
    RefineQueriesOutput,
    RetrieveOutput,
    SupportReplyInput,
    SupportReplyWorkflow,
    ValidateOutput,
    build_context_activity,
    draft_activity,
    persist_reply_activity,
    refine_queries_activity,
    retrieve_activity,
    validate_activity,
)


@pytest.fixture
def sample_chunk_ids() -> list[str]:
    return ["aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"]


@pytest.fixture
def workflow_input() -> SupportReplyInput:
    return SupportReplyInput(team_id=1, ticket_id="deadbeef-0000-0000-0000-000000000001")


PIPELINE_MODULE = "products.conversations.backend.temporal.pipeline"


@pytest.mark.django_db
@pytest.mark.asyncio
@patch(f"{PIPELINE_MODULE}._persist_reply_sync")
@patch(f"{PIPELINE_MODULE}._validate", new_callable=AsyncMock)
@patch(f"{PIPELINE_MODULE}._draft_async", new_callable=AsyncMock)
@patch(f"{PIPELINE_MODULE}._retrieve_sync")
@patch(f"{PIPELINE_MODULE}._refine_queries", new_callable=AsyncMock)
@patch(f"{PIPELINE_MODULE}._build_context_sync")
async def test_workflow_persists_on_high_score(
    mock_build,
    mock_refine,
    mock_retrieve,
    mock_draft,
    mock_validate,
    mock_persist,
    workflow_input,
    sample_chunk_ids,
):
    from temporalio.testing import WorkflowEnvironment
    from temporalio.worker import Worker

    mock_build.return_value = BuildContextOutput(ticket_context="Customer asks about setup", ticket_title="Setup help")
    mock_refine.return_value = RefineQueriesOutput(queries=["how to install"])
    mock_retrieve.return_value = RetrieveOutput(chunk_ids=sample_chunk_ids)
    mock_draft.return_value = DraftOutput(
        reply="You can install via pip.",
        citations=["aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"],
        confidence=0.9,
    )
    mock_validate.return_value = ValidateOutput(grounded=True, coverage=0.9, confidence=0.85, missing=[])

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue="test-queue",
            workflows=[SupportReplyWorkflow],
            activities=[
                build_context_activity,
                refine_queries_activity,
                retrieve_activity,
                draft_activity,
                validate_activity,
                persist_reply_activity,
            ],
        ):
            result = await env.client.execute_workflow(
                SupportReplyWorkflow.run,
                workflow_input,
                id="test-persist-high-score",
                task_queue="test-queue",
            )

    assert "persisted" in result
    assert "confidence=0.85" in result
    assert "attempts=1" in result
    mock_persist.assert_called_once()


@pytest.mark.django_db
@pytest.mark.asyncio
@patch(f"{PIPELINE_MODULE}._persist_reply_sync")
@patch(f"{PIPELINE_MODULE}._validate", new_callable=AsyncMock)
@patch(f"{PIPELINE_MODULE}._draft_async", new_callable=AsyncMock)
@patch(f"{PIPELINE_MODULE}._retrieve_sync")
@patch(f"{PIPELINE_MODULE}._refine_queries", new_callable=AsyncMock)
@patch(f"{PIPELINE_MODULE}._build_context_sync")
async def test_workflow_widens_on_low_score(
    mock_build,
    mock_refine,
    mock_retrieve,
    mock_draft,
    mock_validate,
    mock_persist,
    workflow_input,
    sample_chunk_ids,
):
    from temporalio.testing import WorkflowEnvironment
    from temporalio.worker import Worker

    mock_build.return_value = BuildContextOutput(ticket_context="Question about pricing", ticket_title="Pricing")
    mock_refine.return_value = RefineQueriesOutput(queries=["pricing", "plans"])
    mock_retrieve.return_value = RetrieveOutput(chunk_ids=sample_chunk_ids)
    mock_draft.return_value = DraftOutput(
        reply="Here's pricing info.",
        citations=["aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"],
        confidence=0.7,
    )

    validate_count = {"n": 0}

    def validate_side_effect(*args, **kwargs):
        validate_count["n"] += 1
        if validate_count["n"] < 3:
            return ValidateOutput(grounded=False, coverage=0.4, confidence=0.3, missing=["pricing info"])
        return ValidateOutput(grounded=True, coverage=0.9, confidence=0.8, missing=[])

    mock_validate.side_effect = validate_side_effect

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue="test-queue",
            workflows=[SupportReplyWorkflow],
            activities=[
                build_context_activity,
                refine_queries_activity,
                retrieve_activity,
                draft_activity,
                validate_activity,
                persist_reply_activity,
            ],
        ):
            result = await env.client.execute_workflow(
                SupportReplyWorkflow.run,
                workflow_input,
                id="test-widen-low-score",
                task_queue="test-queue",
            )

    assert "persisted" in result
    assert validate_count["n"] == 3
    assert mock_refine.call_count >= 3


@pytest.mark.django_db
@pytest.mark.asyncio
@patch(f"{PIPELINE_MODULE}._persist_reply_sync")
@patch(f"{PIPELINE_MODULE}._validate", new_callable=AsyncMock)
@patch(f"{PIPELINE_MODULE}._draft_async", new_callable=AsyncMock)
@patch(f"{PIPELINE_MODULE}._retrieve_sync")
@patch(f"{PIPELINE_MODULE}._refine_queries", new_callable=AsyncMock)
@patch(f"{PIPELINE_MODULE}._build_context_sync")
async def test_workflow_escalates_after_max_attempts(
    mock_build,
    mock_refine,
    mock_retrieve,
    mock_draft,
    mock_validate,
    mock_persist,
    workflow_input,
    sample_chunk_ids,
):
    from temporalio.testing import WorkflowEnvironment
    from temporalio.worker import Worker

    mock_build.return_value = BuildContextOutput(ticket_context="Complex question", ticket_title="Complex")
    mock_refine.return_value = RefineQueriesOutput(queries=["complex topic"])
    mock_retrieve.return_value = RetrieveOutput(chunk_ids=sample_chunk_ids)
    mock_draft.return_value = DraftOutput(
        reply="Partial answer.",
        citations=["aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"],
        confidence=0.4,
    )
    mock_validate.return_value = ValidateOutput(grounded=False, coverage=0.3, confidence=0.2, missing=["everything"])

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue="test-queue",
            workflows=[SupportReplyWorkflow],
            activities=[
                build_context_activity,
                refine_queries_activity,
                retrieve_activity,
                draft_activity,
                validate_activity,
                persist_reply_activity,
            ],
        ):
            result = await env.client.execute_workflow(
                SupportReplyWorkflow.run,
                workflow_input,
                id="test-escalate-max-attempts",
                task_queue="test-queue",
            )

    assert "escalated_with_best" in result
    assert mock_validate.call_count == MAX_ATTEMPTS
    mock_persist.assert_called_once()


@pytest.mark.django_db
@pytest.mark.asyncio
@patch(f"{PIPELINE_MODULE}._persist_reply_sync")
@patch(f"{PIPELINE_MODULE}._validate", new_callable=AsyncMock)
@patch(f"{PIPELINE_MODULE}._draft_async", new_callable=AsyncMock)
@patch(f"{PIPELINE_MODULE}._retrieve_sync")
@patch(f"{PIPELINE_MODULE}._refine_queries", new_callable=AsyncMock)
@patch(f"{PIPELINE_MODULE}._build_context_sync")
async def test_workflow_drafts_via_mcp_when_no_seed_chunks(
    mock_build,
    mock_refine,
    mock_retrieve,
    mock_draft,
    mock_validate,
    mock_persist,
    workflow_input,
):
    from temporalio.testing import WorkflowEnvironment
    from temporalio.worker import Worker

    mock_build.return_value = BuildContextOutput(ticket_context="Off-topic question", ticket_title="Off-topic")
    mock_refine.return_value = RefineQueriesOutput(queries=["unrelated"])
    # Empty seed retrieval must NOT short-circuit — the draft agent has MCP tools and runs anyway.
    mock_retrieve.return_value = RetrieveOutput(chunk_ids=[])
    mock_draft.return_value = DraftOutput(reply="I cannot answer this.", citations=[], confidence=0.0)
    mock_validate.return_value = ValidateOutput(grounded=False, coverage=0.0, confidence=0.0, missing=["everything"])

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue="test-queue",
            workflows=[SupportReplyWorkflow],
            activities=[
                build_context_activity,
                refine_queries_activity,
                retrieve_activity,
                draft_activity,
                validate_activity,
                persist_reply_activity,
            ],
        ):
            result = await env.client.execute_workflow(
                SupportReplyWorkflow.run,
                workflow_input,
                id="test-no-chunks-draft-via-mcp",
                task_queue="test-queue",
            )

    # Agent ran via MCP but couldn't find anything (confidence 0) → escalates without persisting.
    assert result == "escalated_no_reply"
    mock_draft.assert_called()
    mock_persist.assert_not_called()


@pytest.mark.django_db
class TestPersistReplyActivity:
    def test_creates_private_ai_comment(self):
        from posthog.models.comment import Comment
        from posthog.models.organization import Organization
        from posthog.models.team.team import Team

        from products.conversations.backend.temporal.pipeline import _persist_reply_sync

        org = Organization.objects.create(name="Test Org")
        team = Team.objects.create(organization=org, name="Test Team")

        _persist_reply_sync(
            team_id=team.id,
            ticket_id="test-ticket-id",
            reply="Here's how to do X.",
            citations=["chunk-1", "chunk-2"],
            confidence=0.85,
        )

        comment = Comment.objects.get(team_id=team.id, item_id="test-ticket-id")
        assert comment.content == "Here's how to do X."
        assert comment.scope == "conversations_ticket"
        assert comment.item_context is not None
        assert comment.item_context["author_type"] == "AI"
        assert comment.item_context["is_private"] is True
        assert comment.item_context["citations"] == ["chunk-1", "chunk-2"]
        assert comment.item_context["confidence"] == 0.85


class TestStripJsonFence:
    @parameterized.expand(
        [
            ("plain_json", '{"grounded": true}', '{"grounded": true}'),
            ("json_fence", '```json\n{"grounded": true}\n```', '{"grounded": true}'),
            ("json_fence_no_newline", '```json{"grounded": true}```', '{"grounded": true}'),
            ("plain_fence", '```\n{"grounded": true}\n```', '{"grounded": true}'),
            ("uppercase_json", '```JSON\n{"grounded": true}\n```', '{"grounded": true}'),
            ("with_whitespace", '  ```json\n{"grounded": true}\n```  ', '{"grounded": true}'),
            (
                "nested_content",
                '```json\n{\n  "grounded": true,\n  "missing": []\n}\n```',
                '{\n  "grounded": true,\n  "missing": []\n}',
            ),
            (
                "trailing_text_after_fence",
                '```json\n{"grounded": true}\n```\n\nHere is a summary.',
                '{"grounded": true}',
            ),
        ]
    )
    def test_strips_fence_correctly(self, _name, input_text, expected):
        from products.conversations.backend.temporal.pipeline import _strip_json_fence

        assert _strip_json_fence(input_text) == expected


def _mock_gateway_client(text: str) -> MagicMock:
    """Build a mock Anthropic gateway client whose messages.create returns `text`."""
    block = MagicMock()
    block.type = "text"
    block.text = text
    message = MagicMock()
    message.content = [block]
    client = MagicMock()
    client.messages.create = AsyncMock(return_value=message)
    return client


class TestValidateActivity:
    @parameterized.expand(
        [
            (
                "valid_json",
                '{"grounded": true, "coverage": 0.8, "confidence": 0.75, "missing": ["deployment details"]}',
                True,
                0.8,
                0.75,
                ["deployment details"],
            ),
            (
                "json_in_fence",
                '```json\n{"grounded": true, "coverage": 0.9, "confidence": 0.85, "missing": []}\n```',
                True,
                0.9,
                0.85,
                [],
            ),
            (
                "partial_fields",
                '{"grounded": false, "coverage": 0.5}',
                False,
                0.5,
                0.0,
                [],
            ),
        ]
    )
    @pytest.mark.asyncio
    async def test_parses_llm_response(
        self,
        _name,
        llm_response,
        expected_grounded,
        expected_coverage,
        expected_confidence,
        expected_missing,
    ):
        from products.conversations.backend.temporal.pipeline import _validate

        cited = [{"chunk_id": "chunk-1", "content": "Docker compose deployment guide"}]
        with (
            patch(
                f"{PIPELINE_MODULE}.get_async_anthropic_gateway_client", return_value=_mock_gateway_client(llm_response)
            ),
            patch(f"{PIPELINE_MODULE}._hydrate_chunks", return_value=cited),
        ):
            result = await _validate(
                team_id=1,
                ticket_context="How to deploy?",
                reply="Use docker compose.",
                citations=["chunk-1"],
                chunk_ids=["chunk-1"],
            )

        assert result.grounded is expected_grounded
        assert result.coverage == expected_coverage
        assert result.confidence == expected_confidence
        assert result.missing == expected_missing

    @parameterized.expand(
        [
            ("invalid_json", "not valid json at all"),
            ("empty_string", ""),
            ("html_response", "<html><body>Error</body></html>"),
            ("truncated_json", '{"grounded": true, "coverage":'),
        ]
    )
    @pytest.mark.asyncio
    async def test_returns_zero_on_parse_failure(self, _name, llm_response):
        from products.conversations.backend.temporal.pipeline import _validate

        with (
            patch(
                f"{PIPELINE_MODULE}.get_async_anthropic_gateway_client", return_value=_mock_gateway_client(llm_response)
            ),
            patch(f"{PIPELINE_MODULE}._hydrate_chunks", return_value=[]),
        ):
            result = await _validate(
                team_id=1,
                ticket_context="Question",
                reply="Answer",
                citations=[],
                chunk_ids=[],
            )

        assert result.grounded is False
        assert result.confidence == 0.0
        assert "parse_failure" in result.missing
