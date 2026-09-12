from datetime import datetime
from typing import cast
from uuid import UUID

import pytest
from unittest.mock import MagicMock, patch

from asgiref.sync import sync_to_async
from temporalio.common import MetricMeter
from temporalio.testing import ActivityEnvironment

from posthog.api.embedding_worker import EmbeddingResponse
from posthog.models.team import Team

from products.business_knowledge.backend import learning_settings, logic
from products.business_knowledge.backend.learning.contracts import EvidenceBundle, EvidenceRef, evidence_key_for
from products.business_knowledge.backend.models import KnowledgeDocument, KnowledgeLearningRun, LearningRunResult
from products.business_knowledge.backend.temporal.learning.activities.analyze import (
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
    ExtractedKnowledge,
    PiiVerdict,
    PromotionDecision,
)

_TICKET_ID = UUID("10000000-0000-4000-8000-000000000001")
_COMMENT_ID = UUID("20000000-0000-4000-8000-000000000002")
_MODULE = "products.business_knowledge.backend.temporal.learning.activities.analyze"


class _Provider:
    name = "conversations"

    def __init__(self, bundle: EvidenceBundle | None) -> None:
        self.bundle = bundle

    def collect(self, team_id: int, *, since: datetime, limit: int) -> list[EvidenceRef]:
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

    assert sum(len(value) for value in rendered[0].values()) == LEARNING_MAX_SEARCH_CONTEXT_CHARS


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
        assert result.result == "knowledge_created"
        assert result.rejection_code == "none"
        assert run.result == LearningRunResult.KNOWLEDGE_CREATED
        assert run.knowledge_document_id == document.id
        assert document.title == "Refund policy"
        assert document.content == "Refunds are available within 30 days."
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
    def test_model_pii_rejection_is_fail_closed(
        self,
        team: Team,
        pii_result: PiiVerdict,
    ) -> None:
        run, input = _setup_sync(team)
        provider = _Provider(EvidenceBundle(replies=("Use the standard contact process.",)))
        model = MagicMock()
        structured_model = model.with_structured_output.return_value
        structured_model.invoke.return_value = pii_result

        with (
            patch(f"{_MODULE}.get_learning_provider", return_value=provider),
            patch(
                f"{_MODULE}._extract_candidate",
                return_value=_extraction(
                    canonical_topic="Contact policy",
                    canonical_answer="Contact Taylor for help.",
                ),
            ),
            patch(f"{_MODULE}._build_model", return_value=model),
            patch(f"{_MODULE}.generate_embedding") as embed,
            patch(f"{_MODULE}.logic.search_knowledge") as search,
            patch(f"{_MODULE}.logic.create_generated_knowledge_document") as publish,
        ):
            result = analyze_learning_evidence(input)

        run.refresh_from_db()
        assert result.rejection_code == "pii"
        assert run.result == LearningRunResult.NO_KNOWLEDGE
        model.with_structured_output.assert_called_once_with(PiiVerdict, method="json_schema", include_raw=False)
        structured_model.invoke.assert_called_once()
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

    def test_unexpected_structured_extraction_marks_run_failed(self, team: Team) -> None:
        run, input = _setup_sync(team)
        provider = _Provider(EvidenceBundle(replies=("Refunds are available within 30 days.",)))
        model = MagicMock()
        structured_model = model.with_structured_output.return_value
        structured_model.invoke.return_value = None

        with (
            patch(f"{_MODULE}.get_learning_provider", return_value=provider),
            patch(f"{_MODULE}._build_model", return_value=model),
            pytest.raises(LearningAnalysisError, match="invalid_extraction_output"),
        ):
            analyze_learning_evidence(input)

        run.refresh_from_db()
        assert run.status == "failed"
        assert run.error == "invalid_extraction_output"
        model.with_structured_output.assert_called_once_with(
            ExtractedKnowledge,
            method="json_schema",
            include_raw=False,
        )

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

    def test_missing_run_raises_bounded_error(self, team: Team) -> None:
        run, input = _setup_sync(team)
        run.delete()

        with pytest.raises(LearningAnalysisError, match="run_not_found"):
            analyze_learning_evidence(input)
