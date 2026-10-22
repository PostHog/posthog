from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

import pytest
from unittest.mock import MagicMock, patch

import httpx
import anthropic
from anthropic.types import ToolUseBlock
from asgiref.sync import sync_to_async
from structlog.testing import capture_logs
from temporalio.common import MetricMeter
from temporalio.testing import ActivityEnvironment

from posthog.api.embedding_worker import EmbeddingResponse
from posthog.models.team import Team

from products.business_knowledge.backend import learning_settings, logic
from products.business_knowledge.backend.learning.contracts import EvidenceBundle, EvidenceRef, evidence_key_for
from products.business_knowledge.backend.models import (
    KnowledgeDocument,
    KnowledgeLearningRun,
    KnowledgeSource,
    LearningRunResult,
)
from products.business_knowledge.backend.temporal.learning.activities.analyze import (
    _MODEL_TIMEOUT_SECONDS,
    LearningAnalysisError,
    _render_search_context,
    analyze_learning_evidence,
    analyze_learning_evidence_activity,
)
from products.business_knowledge.backend.temporal.learning.constants import (
    ANALYSIS_VERSION,
    LEARNING_MAX_SEARCH_CONTEXT_CHARS,
)
from products.business_knowledge.backend.temporal.learning.schemas import (
    AnalyzeLearningEvidenceInput,
    ContradictionVerdict,
    ExtractedKnowledge,
    PiiVerdict,
    PromotionDecision,
)

_TICKET_ID = UUID("10000000-0000-4000-8000-000000000001")
_COMMENT_ID = UUID("20000000-0000-4000-8000-000000000002")
_MODULE = "products.business_knowledge.backend.temporal.learning.activities.analyze"
_OLD_TICKET_ID = UUID("10000000-0000-4000-8000-000000000007")
_OLD_COMMENT_ID = UUID("20000000-0000-4000-8000-000000000008")
_REVISION_AT = datetime(2026, 1, 1, tzinfo=UTC)


class _Provider:
    name = "conversations"

    def __init__(self, bundle: EvidenceBundle | None) -> None:
        self.bundle = bundle

    def collect(
        self,
        team_id: int,
        *,
        since: datetime,
        limit: int,
        offset: int = 0,
        ticket_id: UUID | None = None,
    ) -> list[EvidenceRef]:
        return []

    def load(self, ref: EvidenceRef) -> EvidenceBundle | None:
        return self.bundle


class _RecordingMetric:
    def __init__(self, sink: list[tuple[str, int, dict[str, str]]], name: str, attributes: dict[str, str]) -> None:
        self.sink = sink
        self.name = name
        self.attributes = attributes

    def add(self, value: int) -> None:
        self.sink.append((self.name, value, self.attributes))


class _RecordingMetricMeter:
    def __init__(
        self,
        sink: list[tuple[str, int, dict[str, str]]],
        attributes: dict[str, str] | None = None,
    ) -> None:
        self.sink = sink
        self.attributes = attributes or {}

    def with_additional_attributes(self, attributes: dict[str, str]) -> "_RecordingMetricMeter":
        return _RecordingMetricMeter(self.sink, {**self.attributes, **attributes})

    def create_counter(self, name: str, description: str) -> _RecordingMetric:
        return _RecordingMetric(self.sink, name, self.attributes)


def _evidence(*, ticket_number: int = 42) -> EvidenceRef:
    return EvidenceRef(
        evidence_key=evidence_key_for(_TICKET_ID, _COMMENT_ID),
        source_team_id=1,
        display_label=f"ticket #{ticket_number}",
        deep_link=f"https://example.com/tickets/{ticket_number}",
        provider="conversations",
        ticket_id=_TICKET_ID,
        ticket_number=ticket_number,
        resolution_comment_id=_COMMENT_ID,
        revision_at=_REVISION_AT,
    )


def _extraction(**overrides: object) -> ExtractedKnowledge:
    payload: dict[str, object] = {
        "canonical_topic": "Refund policy",
        "canonical_answer": "Refunds are available within 30 days.",
        "generalizable": True,
        "useful": True,
        "supported_by_public_human_resolution": True,
        "confidence": 0.95,
        "rejection_code": "none",
    }
    payload.update(overrides)
    return ExtractedKnowledge.model_validate(payload)


def _promotion(**overrides: object) -> PromotionDecision:
    payload: dict[str, object] = {
        "generalizable": True,
        "useful": True,
        "supported_by_public_human_resolution": True,
        "missing_from_business_knowledge": True,
        "confidence": 0.93,
        "rejection_code": "none",
    }
    payload.update(overrides)
    return PromotionDecision.model_validate(payload)


def _contradiction(**overrides: object) -> ContradictionVerdict:
    payload: dict[str, object] = {
        "is_contradiction": True,
        "confidence": 0.91,
    }
    payload.update(overrides)
    return ContradictionVerdict.model_validate(payload)


def _existing_result(source: KnowledgeSource, content: str) -> logic.KnowledgeSearchResult:
    document = KnowledgeDocument.objects.unscoped().filter(source_id=source.id).order_by("created_at").first()
    return logic.KnowledgeSearchResult(
        chunk_id=UUID("30000000-0000-4000-8000-000000000003"),
        source_id=source.id,
        source_name=source.name,
        source_type=source.source_type,
        document_id=document.id if document is not None else UUID("50000000-0000-4000-8000-000000000005"),
        is_generated=source.is_generated,
        document_title=source.name,
        heading_path="",
        ordinal=0,
        content=content,
    )


def _provider_status_error() -> Exception:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return anthropic.AuthenticationError(
        "sensitive model output",
        response=httpx.Response(401, request=request, headers={"request-id": "req_test"}),
        body={"type": "error", "error": {"type": "authentication_error", "message": "sensitive model output"}},
    )


def _provider_connection_error() -> Exception:
    error = anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com/v1/messages"))
    error.__cause__ = httpx.ProxyError("sensitive model output")
    return error


def _tool_response(name: str, payload: dict[str, object]) -> MagicMock:
    response = MagicMock()
    response.content = [ToolUseBlock(id="toolu_test", name=name, input=payload, type="tool_use")]
    return response


def _invalid_extraction_response() -> MagicMock:
    return _tool_response(
        "ExtractedKnowledge",
        {
            **_extraction().model_dump(),
            "canonical_answer": "",
            "rejection_code": "sensitive model output",
            "sensitive model output": True,
        },
    )


def _gateway_client() -> tuple[MagicMock, MagicMock]:
    client = MagicMock()
    entered = client.with_options.return_value.__enter__.return_value
    return client, entered


def _embedding() -> EmbeddingResponse:
    return EmbeddingResponse(embedding=[0.1, 0.2], tokens_used=4, did_truncate=False)


def _create_run(team: Team, evidence: EvidenceRef) -> KnowledgeLearningRun:
    return KnowledgeLearningRun.objects.for_team(team.id).create(
        team=team,
        provider=evidence.provider,
        evidence_key=evidence.evidence_key,
        source_team_id=evidence.source_team_id,
        analysis_version=ANALYSIS_VERSION,
    )


def _setup_sync(team: Team) -> tuple[KnowledgeLearningRun, AnalyzeLearningEvidenceInput]:
    team.organization.is_ai_data_processing_approved = True
    team.organization.save(update_fields=["is_ai_data_processing_approved"])
    learning_settings.set_learn_from_support_enabled(team, True)
    evidence = _evidence()
    evidence = EvidenceRef(
        evidence_key=evidence.evidence_key,
        source_team_id=team.id,
        display_label=evidence.display_label,
        deep_link=evidence.deep_link,
        provider=evidence.provider,
        ticket_id=evidence.ticket_id,
        ticket_number=evidence.ticket_number,
        resolution_comment_id=evidence.resolution_comment_id,
        revision_at=evidence.revision_at,
    )
    run = _create_run(team, evidence)
    return run, AnalyzeLearningEvidenceInput(team_id=team.id, run_id=str(run.id), evidence=evidence)


async def _setup(team: Team) -> tuple[KnowledgeLearningRun, AnalyzeLearningEvidenceInput]:
    return await sync_to_async(_setup_sync)(team)


def test_search_context_budget_includes_titles_and_headings() -> None:
    result = logic.KnowledgeSearchResult(
        chunk_id=UUID("30000000-0000-4000-8000-000000000003"),
        source_id=UUID("40000000-0000-4000-8000-000000000004"),
        source_name="Policies",
        source_type="text",
        document_id=UUID("50000000-0000-4000-8000-000000000005"),
        document_title="t" * 512,
        heading_path="h" * 1024,
        ordinal=0,
        content="c" * LEARNING_MAX_SEARCH_CONTEXT_CHARS,
    )

    rendered = _render_search_context([result])

    assert rendered[0]["index"] == 0
    assert (
        sum(len(value) for value in rendered[0].values() if isinstance(value, str)) == LEARNING_MAX_SEARCH_CONTEXT_CHARS
    )


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
class TestLearningAnalyzerActivity:
    async def test_publishes_useful_missing_knowledge_and_completes_run(self, team: Team) -> None:
        run, input = await _setup(team)
        provider = _Provider(EvidenceBundle(replies=("Refunds are available within 30 days.",)))
        recorded_metrics: list[tuple[str, int, dict[str, str]]] = []
        environment = ActivityEnvironment()
        environment.metric_meter = cast(MetricMeter, _RecordingMetricMeter(recorded_metrics))

        with (
            patch(f"{_MODULE}.get_learning_provider", return_value=provider),
            patch(
                f"{_MODULE}._invoke_structured_model",
                side_effect=[_extraction(), PiiVerdict(verdict="safe"), _promotion()],
            ),
            patch(f"{_MODULE}.generate_embedding", return_value=_embedding()),
            patch(f"{_MODULE}.logic.search_knowledge", return_value=[]),
        ):
            result = await environment.run(analyze_learning_evidence_activity, input)

        await sync_to_async(run.refresh_from_db)()
        document = await sync_to_async(KnowledgeDocument.objects.unscoped().get)(id=result.knowledge_document_id)
        source = await sync_to_async(KnowledgeSource.objects.unscoped().get)(id=document.source_id)
        assert result.result == "knowledge_created"
        assert result.rejection_code == "none"
        assert run.result == LearningRunResult.KNOWLEDGE_CREATED
        assert run.knowledge_document_id == document.id
        assert document.title == "Refund policy"
        assert document.content == "Refunds are available within 30 days."
        assert source.name == "Refund policy"
        assert source.is_generated is True
        generated_count = await sync_to_async(
            lambda: KnowledgeSource.objects.unscoped().filter(team_id=document.team_id, is_generated=True).count()
        )()
        assert generated_count == 1
        assert document.metadata["ticket_id"] == str(_TICKET_ID)
        assert str(_TICKET_ID) not in f"{document.title}\n{document.content}"
        assert [(name, value, attributes["outcome"]) for name, value, attributes in recorded_metrics] == [
            ("business_knowledge_learning_total", 1, "analyzed"),
            ("business_knowledge_learning_total", 1, "published"),
        ]


@pytest.mark.django_db
class TestLearningAnalyzer:
    @pytest.mark.parametrize(
        "overrides,expected_code",
        [
            ({"generalizable": False, "rejection_code": "case_specific"}, "case_specific"),
            ({"useful": False, "rejection_code": "not_useful"}, "not_useful"),
            (
                {"supported_by_public_human_resolution": False, "rejection_code": "unsupported"},
                "unsupported",
            ),
            ({"confidence": 0.4, "rejection_code": "low_confidence"}, "low_confidence"),
        ],
    )
    def test_extraction_rejections_never_search_or_publish(
        self,
        team: Team,
        overrides: dict[str, object],
        expected_code: str,
    ) -> None:
        run, input = _setup_sync(team)
        provider = _Provider(EvidenceBundle(replies=("This answer applies only to the current case.",)))

        with (
            patch(f"{_MODULE}.get_learning_provider", return_value=provider),
            patch(f"{_MODULE}._invoke_structured_model", return_value=_extraction(**overrides)),
            patch(f"{_MODULE}.generate_embedding") as embed,
            patch(f"{_MODULE}.logic.search_knowledge") as search,
            patch(f"{_MODULE}.logic.create_generated_knowledge_document") as publish,
        ):
            result = analyze_learning_evidence(input)

        run.refresh_from_db()
        assert result.result == "no_knowledge"
        assert result.rejection_code == expected_code
        assert run.result == LearningRunResult.NO_KNOWLEDGE
        embed.assert_not_called()
        search.assert_not_called()
        publish.assert_not_called()

    @pytest.mark.parametrize(
        "pii_result",
        [PiiVerdict(verdict="unsafe"), PiiVerdict(verdict="uncertain")],
    )
    def test_model_pii_rejection_is_fail_closed(self, team: Team, pii_result: PiiVerdict) -> None:
        run, input = _setup_sync(team)
        provider = _Provider(EvidenceBundle(replies=("Use the standard contact process.",)))
        client, entered = _gateway_client()
        extraction = _extraction(canonical_topic="Contact policy", canonical_answer="Contact Taylor for help.")
        entered.messages.create.side_effect = [
            _tool_response("ExtractedKnowledge", extraction.model_dump()),
            _tool_response("PiiVerdict", pii_result.model_dump()),
        ]

        with (
            patch(f"{_MODULE}.get_learning_provider", return_value=provider),
            patch(f"{_MODULE}.build_ai_gateway_anthropic_client", return_value=client) as builder,
            patch(f"{_MODULE}.generate_embedding") as embed,
            patch(f"{_MODULE}.logic.search_knowledge") as search,
            patch(f"{_MODULE}.logic.create_generated_knowledge_document") as publish,
        ):
            result = analyze_learning_evidence(input)

        run.refresh_from_db()
        assert result.rejection_code == "pii"
        assert run.result == LearningRunResult.NO_KNOWLEDGE
        assert [call.kwargs["properties"]["ai_feature"] for call in builder.call_args_list] == [
            "support_learning_extraction",
            "support_learning_pii",
        ]
        for call in builder.call_args_list:
            assert call.kwargs["ai_product"] == "business_knowledge"
            assert call.kwargs["distinct_id"] == f"team-{team.id}"
            assert call.kwargs["trace_id"] == str(run.id)
            assert call.kwargs["team_id"] == team.id
            assert call.kwargs["properties"]["learning_run_id"] == str(run.id)
        client.with_options.assert_called_with(timeout=_MODEL_TIMEOUT_SECONDS, max_retries=0)
        assert entered.messages.create.call_args_list[0].kwargs["tools"][0]["input_schema"] == (
            ExtractedKnowledge.model_json_schema()
        )
        for call in entered.messages.create.call_args_list:
            assert call.kwargs["extra_headers"] == {"X-PostHog-Privacy-Mode": "true"}
            assert call.kwargs["tool_choice"]["type"] == "tool"
        embed.assert_not_called()
        search.assert_not_called()
        publish.assert_not_called()

    @pytest.mark.parametrize(
        "known_content",
        [
            "Refunds are available within 30 days.",
            "Customers can request their money back during the first month.",
        ],
    )
    def test_existing_or_semantically_equivalent_knowledge_is_not_published(
        self,
        team: Team,
        known_content: str,
    ) -> None:
        run, input = _setup_sync(team)
        provider = _Provider(EvidenceBundle(replies=("Refunds are available within 30 days.",)))
        search_result = logic.KnowledgeSearchResult(
            chunk_id=UUID("30000000-0000-4000-8000-000000000003"),
            source_id=UUID("40000000-0000-4000-8000-000000000004"),
            source_name="Policies",
            source_type="text",
            document_id=UUID("50000000-0000-4000-8000-000000000005"),
            document_title="Returns",
            heading_path="",
            ordinal=0,
            content=known_content,
        )

        with (
            patch(f"{_MODULE}.get_learning_provider", return_value=provider),
            patch(
                f"{_MODULE}._invoke_structured_model",
                side_effect=[
                    _extraction(),
                    PiiVerdict(verdict="safe"),
                    _promotion(missing_from_business_knowledge=False, rejection_code="already_known"),
                ],
            ) as invoke,
            patch(f"{_MODULE}.generate_embedding", return_value=_embedding()),
            patch(f"{_MODULE}.logic.search_knowledge", return_value=[search_result]) as search,
            patch(f"{_MODULE}.logic.create_generated_knowledge_document") as publish,
        ):
            result = analyze_learning_evidence(input)

        run.refresh_from_db()
        assert result.rejection_code == "already_known"
        assert run.result == LearningRunResult.NO_KNOWLEDGE
        assert invoke.call_args_list[2].kwargs["payload"]["retrieved_business_knowledge"][0]["index"] == 0
        assert invoke.call_args_list[2].kwargs["payload"]["retrieved_business_knowledge"][0]["content"] == known_content
        assert invoke.call_args_list[2].kwargs["payload"]["public_human_replies"] == [
            "Refunds are available within 30 days."
        ]
        assert search.call_args.kwargs["use_semantic"] is True
        assert search.call_args.kwargs["query_embedding"] == [0.1, 0.2]
        publish.assert_not_called()

    def test_promotion_rechecks_evidence_support_before_publication(self, team: Team) -> None:
        run, input = _setup_sync(team)
        provider = _Provider(EvidenceBundle(replies=("Refunds are available within 30 days.",)))

        with (
            patch(f"{_MODULE}.get_learning_provider", return_value=provider),
            patch(
                f"{_MODULE}._invoke_structured_model",
                side_effect=[
                    _extraction(),
                    PiiVerdict(verdict="safe"),
                    _promotion(supported_by_public_human_resolution=False, rejection_code="unsupported"),
                ],
            ),
            patch(f"{_MODULE}.generate_embedding", return_value=_embedding()),
            patch(f"{_MODULE}.logic.search_knowledge", return_value=[]),
            patch(f"{_MODULE}.logic.create_generated_knowledge_document") as publish,
        ):
            result = analyze_learning_evidence(input)

        run.refresh_from_db()
        assert result.rejection_code == "unsupported"
        assert run.result == LearningRunResult.NO_KNOWLEDGE
        publish.assert_not_called()

    def test_embedding_failure_fails_closed_before_promotion(self, team: Team) -> None:
        run, input = _setup_sync(team)
        provider = _Provider(EvidenceBundle(replies=("Refunds are available within 30 days.",)))

        with (
            patch(f"{_MODULE}.get_learning_provider", return_value=provider),
            patch(
                f"{_MODULE}._invoke_structured_model",
                side_effect=[_extraction(), PiiVerdict(verdict="safe")],
            ) as invoke,
            patch(f"{_MODULE}.generate_embedding", side_effect=RuntimeError("unavailable")),
            patch(f"{_MODULE}.logic.search_knowledge") as search,
            patch(f"{_MODULE}.logic.create_generated_knowledge_document") as publish,
            pytest.raises(LearningAnalysisError, match="knowledge_search_failed"),
        ):
            analyze_learning_evidence(input)

        run.refresh_from_db()
        assert run.status == "failed"
        assert run.error == "knowledge_search_failed"
        assert invoke.call_count == 2
        search.assert_not_called()
        publish.assert_not_called()

    @pytest.mark.parametrize(
        "model_outcome,expected_fields",
        [
            pytest.param(
                _provider_status_error,
                {
                    "error_type": "AuthenticationError",
                    "status_code": 401,
                    "request_id": "req_test",
                    "provider_error_type": "authentication_error",
                },
                id="provider_status",
            ),
            pytest.param(
                _provider_connection_error,
                {"error_type": "APIConnectionError", "cause_type": "ProxyError"},
                id="provider_connection",
            ),
            pytest.param(
                _invalid_extraction_response,
                {
                    "error_type": "ValidationError",
                    "validation_failures": [
                        "canonical_answer:string_too_short",
                        "rejection_code:literal_error",
                        "<other>:extra_forbidden",
                    ],
                },
                id="output_validation",
            ),
        ],
    )
    def test_model_error_marks_run_failed_without_capturing_sensitive_error(
        self,
        team: Team,
        model_outcome: Callable[[], object],
        expected_fields: dict[str, object],
    ) -> None:
        run, input = _setup_sync(team)
        provider = _Provider(EvidenceBundle(replies=("Refunds are available within 30 days.",)))
        client, entered = _gateway_client()
        outcome = model_outcome()
        if isinstance(outcome, Exception):
            entered.messages.create.side_effect = outcome
        else:
            entered.messages.create.return_value = outcome

        with (
            patch(f"{_MODULE}.get_learning_provider", return_value=provider),
            patch(f"{_MODULE}.build_ai_gateway_anthropic_client", return_value=client) as builder,
            capture_logs() as logs,
            pytest.raises(LearningAnalysisError, match="extraction_model_failed") as raised,
        ):
            analyze_learning_evidence(input)

        assert raised.value.__cause__ is None
        run.refresh_from_db()
        assert run.status == "failed"
        assert run.error == "extraction_model_failed"
        failed = [entry for entry in logs if entry["event"] == "business_knowledge.learning.model_failed"]
        assert failed == [
            {
                "event": "business_knowledge.learning.model_failed",
                "log_level": "error",
                "stage": "extraction",
                "team_id": team.id,
                "trace_id": str(run.id),
                **expected_fields,
            }
        ]
        builder.assert_called_once_with(
            ai_product="business_knowledge",
            trace_id=str(run.id),
            distinct_id=f"team-{team.id}",
            team_id=team.id,
            properties={"ai_feature": "support_learning_extraction", "learning_run_id": str(run.id)},
        )
        client.with_options.assert_called_once_with(timeout=_MODEL_TIMEOUT_SECONDS, max_retries=0)
        assert entered.messages.create.call_args.kwargs["extra_headers"] == {"X-PostHog-Privacy-Mode": "true"}

    def test_missing_gateway_config_fails_before_the_model(self, team: Team) -> None:
        run, input = _setup_sync(team)
        provider = _Provider(EvidenceBundle(replies=("Refunds are available within 30 days.",)))

        with (
            patch(f"{_MODULE}.get_learning_provider", return_value=provider),
            patch(
                f"{_MODULE}.build_ai_gateway_anthropic_client",
                side_effect=ValueError("AI_GATEWAY_URL and AI_GATEWAY_API_KEY must be configured"),
            ),
            pytest.raises(LearningAnalysisError, match="ai_gateway_not_configured") as raised,
        ):
            analyze_learning_evidence(input)

        assert raised.value.__cause__ is None
        run.refresh_from_db()
        assert run.error == "ai_gateway_not_configured"

    def test_missing_evidence_completes_as_ineligible(self, team: Team) -> None:
        run, input = _setup_sync(team)

        with (
            patch(f"{_MODULE}.get_learning_provider", return_value=_Provider(None)),
            patch(f"{_MODULE}._invoke_structured_model") as invoke,
        ):
            result = analyze_learning_evidence(input)

        run.refresh_from_db()
        assert result.result == "ineligible"
        assert run.result == LearningRunResult.INELIGIBLE
        invoke.assert_not_called()

    def test_disabled_learning_stops_a_queued_run_before_loading_evidence(self, team: Team) -> None:
        run, input = _setup_sync(team)
        learning_settings.set_learn_from_support_enabled(team, False)

        with (
            patch(f"{_MODULE}.get_learning_provider") as get_provider,
            patch(f"{_MODULE}.logic.create_generated_knowledge_document") as publish,
        ):
            result = analyze_learning_evidence(input)

        run.refresh_from_db()
        assert result.result == "ineligible"
        assert run.result == LearningRunResult.INELIGIBLE
        get_provider.assert_not_called()
        publish.assert_not_called()

    def test_learned_cap_skips_llm_and_completes_without_knowledge(self, team: Team) -> None:
        run, input = _setup_sync(team)

        with (
            patch.object(logic, "MAX_LEARNED_SOURCES_PER_TEAM", 0),
            patch(f"{_MODULE}.get_learning_provider") as get_provider,
            patch(f"{_MODULE}._invoke_structured_model") as invoke,
            patch(f"{_MODULE}.logic.create_generated_knowledge_document") as publish,
        ):
            result = analyze_learning_evidence(input)

        run.refresh_from_db()
        assert result.result == "no_knowledge"
        assert result.rejection_code == "learned_cap_reached"
        assert run.result == LearningRunResult.NO_KNOWLEDGE
        assert run.status == "completed"
        get_provider.assert_not_called()
        invoke.assert_not_called()
        publish.assert_not_called()

    def test_learned_cap_during_publish_does_not_fail_the_run(self, team: Team) -> None:
        run, input = _setup_sync(team)
        provider = _Provider(EvidenceBundle(replies=("Refunds are available within 30 days.",)))

        with (
            patch.object(logic, "can_publish_learned_source", return_value=True),
            patch(f"{_MODULE}.get_learning_provider", return_value=provider),
            patch(
                f"{_MODULE}._invoke_structured_model",
                side_effect=[_extraction(), PiiVerdict(verdict="safe"), _promotion()],
            ),
            patch(f"{_MODULE}.generate_embedding", return_value=_embedding()),
            patch(f"{_MODULE}.logic.search_knowledge", return_value=[]),
            patch(
                f"{_MODULE}.logic.create_generated_knowledge_document",
                side_effect=logic.LearnedSourceCapReached("cap"),
            ) as publish,
        ):
            result = analyze_learning_evidence(input)

        run.refresh_from_db()
        assert result.result == "no_knowledge"
        assert result.rejection_code == "learned_cap_reached"
        assert run.result == LearningRunResult.NO_KNOWLEDGE
        assert run.status == "completed"
        publish.assert_called_once()

    @pytest.mark.parametrize(
        "case,confirm_contradiction,expected_result,expected_code",
        [
            ("newer", True, "superseded", "none"),
            ("stale", True, "no_knowledge", "stale_candidate"),
            ("denied", False, "no_knowledge", "already_known"),
            ("backfilled_row", True, "superseded", "none"),
            ("row_without_recorded_reply_time", True, "superseded", "none"),
            ("already_superseded", True, "no_knowledge", "already_known"),
            ("written_by_a_person", True, "no_knowledge", "already_known"),
        ],
    )
    def test_confirmed_contradiction_keeps_the_newest_fact(
        self,
        team: Team,
        case: str,
        confirm_contradiction: bool,
        expected_result: str,
        expected_code: str,
    ) -> None:
        run, input = _setup_sync(team)
        provider = _Provider(EvidenceBundle(replies=("Refunds are now available within 7 days.",)))
        old_content = "Refunds are available within 15 days."
        recorded_at = _REVISION_AT + timedelta(days=30) if case == "stale" else _REVISION_AT - timedelta(days=30)
        if case == "written_by_a_person":
            old_source = logic.create_text_source(
                team_id=team.id,
                created_by_id=None,
                name="Refund policy",
                text=old_content,
            )
        else:
            learned = logic.create_generated_knowledge_document(
                logic.CreateGeneratedKnowledgeDocument(
                    team_id=team.id,
                    provider="conversations",
                    ticket_id=_OLD_TICKET_ID,
                    ticket_number=7,
                    source_team_id=team.id,
                    resolution_comment_id=_OLD_COMMENT_ID,
                    analysis_version=ANALYSIS_VERSION,
                    title="Refund policy",
                    content=old_content,
                    evidence_revision_at=recorded_at,
                )
            )
            old_source = KnowledgeSource.objects.unscoped().get(id=learned.source_id)
        old_source_id = old_source.id
        old_document = KnowledgeDocument.objects.unscoped().get(source_id=old_source_id)
        KnowledgeDocument.objects.unscoped().filter(id=old_document.id).update(created_at=recorded_at)
        if case == "backfilled_row":
            # The row was written after the incoming reply, but the answer in it is older.
            KnowledgeDocument.objects.unscoped().filter(id=old_document.id).update(
                created_at=_REVISION_AT + timedelta(days=30)
            )
        if case == "row_without_recorded_reply_time":
            # A learned row from before the reply time was recorded falls back to the row time.
            metadata = dict(old_document.metadata or {})
            metadata.pop(logic.EVIDENCE_REVISION_AT_KEY, None)
            KnowledgeDocument.objects.unscoped().filter(id=old_document.id).update(metadata=metadata)
        if case == "already_superseded":
            logic.supersede_knowledge_source(
                team_id=team.id,
                source_id=old_source_id,
                document_id=old_document.id,
                superseded_by_ticket_id=UUID("10000000-0000-4000-8000-000000000009"),
                superseded_by_ticket_number=7,
            )
        search_result = _existing_result(old_source, old_content)
        generated_before = KnowledgeSource.objects.unscoped().filter(team_id=team.id, is_generated=True).count()

        with (
            patch(f"{_MODULE}.get_learning_provider", return_value=provider),
            patch(
                f"{_MODULE}._invoke_structured_model",
                side_effect=[
                    _extraction(canonical_answer="Refunds are available within 7 days."),
                    PiiVerdict(verdict="safe"),
                    _promotion(contradicts_existing=True, conflicting_index=0),
                    _contradiction(is_contradiction=confirm_contradiction),
                ],
            ) as invoke,
            patch(f"{_MODULE}.generate_embedding", return_value=_embedding()),
            patch(f"{_MODULE}.logic.search_knowledge", return_value=[search_result]),
            patch(f"{_MODULE}._increment_counter") as increment,
        ):
            result = analyze_learning_evidence(input)

        run.refresh_from_db()
        old_source = KnowledgeSource.objects.unscoped().get(id=old_source_id)
        assert result.result == expected_result
        assert result.rejection_code == expected_code
        assert invoke.call_args_list[3].kwargs["stage"] == "contradiction"
        outcomes = [call.args[0] for call in increment.call_args_list]
        generated_now = KnowledgeSource.objects.unscoped().filter(team_id=team.id, is_generated=True).count()
        if expected_result == "superseded":
            assert result.knowledge_document_id is not None
            document = KnowledgeDocument.objects.unscoped().get(id=result.knowledge_document_id)
            published_source = KnowledgeSource.objects.unscoped().get(id=document.source_id)
            assert run.result == LearningRunResult.SUPERSEDED
            assert document.content == "Refunds are available within 7 days."
            assert old_source.status == "error"
            assert old_source.error_message == logic.SUPERSEDED_SOURCE_MESSAGE
            assert old_source.id != published_source.id
            assert KnowledgeDocument.objects.unscoped().get(source_id=old_source.id).content == old_content
            assert "superseded" in outcomes
        elif case == "already_superseded":
            # Another reply won the race, so this one must not leave a second answer in search.
            assert run.result == LearningRunResult.NO_KNOWLEDGE
            assert result.knowledge_document_id is None
            assert generated_now == generated_before
            assert "rejected_already_known" in outcomes
        else:
            assert run.result == LearningRunResult.NO_KNOWLEDGE
            assert result.knowledge_document_id is None
            assert old_source.status != "error"
            assert old_source.error_message == ""
            assert generated_now == generated_before
            assert ("rejected_stale_candidate" if case == "stale" else "rejected_already_known") in outcomes

    def test_a_conflicting_source_deleted_mid_publication_still_publishes(self, team: Team) -> None:
        run, input = _setup_sync(team)
        provider = _Provider(EvidenceBundle(replies=("Refunds are now available within 7 days.",)))
        old_content = "Refunds are available within 15 days."
        learned = logic.create_generated_knowledge_document(
            logic.CreateGeneratedKnowledgeDocument(
                team_id=team.id,
                provider="conversations",
                ticket_id=_OLD_TICKET_ID,
                ticket_number=7,
                source_team_id=team.id,
                resolution_comment_id=_OLD_COMMENT_ID,
                analysis_version=ANALYSIS_VERSION,
                title="Refund policy",
                content=old_content,
                evidence_revision_at=_REVISION_AT - timedelta(days=30),
            )
        )
        old_source = KnowledgeSource.objects.unscoped().get(id=learned.source_id)
        search_result = _existing_result(old_source, old_content)

        def delete_then_report_age(*, team_id: int, document_id: UUID) -> datetime:
            # A person deletes the older source between the recency read and the supersession lock.
            KnowledgeSource.objects.unscoped().filter(id=learned.source_id).delete()
            return _REVISION_AT - timedelta(days=30)

        with (
            patch(f"{_MODULE}.get_learning_provider", return_value=provider),
            patch(
                f"{_MODULE}._invoke_structured_model",
                side_effect=[
                    _extraction(canonical_answer="Refunds are available within 7 days."),
                    PiiVerdict(verdict="safe"),
                    _promotion(contradicts_existing=True, conflicting_index=0),
                    _contradiction(),
                ],
            ),
            patch(f"{_MODULE}.generate_embedding", return_value=_embedding()),
            patch(f"{_MODULE}.logic.search_knowledge", return_value=[search_result]),
            patch(f"{_MODULE}.logic.get_knowledge_fact_recorded_at", side_effect=delete_then_report_age),
        ):
            result = analyze_learning_evidence(input)

        run.refresh_from_db()
        assert result.result == "knowledge_created"
        assert result.rejection_code == "none"
        assert run.result == LearningRunResult.KNOWLEDGE_CREATED
        assert result.knowledge_document_id is not None
        document = KnowledgeDocument.objects.unscoped().get(id=result.knowledge_document_id)
        assert document.content == "Refunds are available within 7 days."
        assert not KnowledgeSource.objects.unscoped().filter(id=learned.source_id).exists()

    def test_missing_run_raises_bounded_error(self, team: Team) -> None:
        run, input = _setup_sync(team)
        run.delete()

        with pytest.raises(LearningAnalysisError, match="run_not_found"):
            analyze_learning_evidence(input)
