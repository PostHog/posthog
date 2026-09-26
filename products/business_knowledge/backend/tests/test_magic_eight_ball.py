import json
from dataclasses import replace
from uuid import uuid4

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized
from rest_framework import status

from posthog.llm.gateway_client import GatewayNotConfiguredError

from products.business_knowledge.backend import logic
from products.business_knowledge.backend.magic_eight_ball import (
    ANSWER_QUESTION_ID,
    EIGHT_BALL_ANSWERS,
    MAGIC_EIGHT_BALL_FEATURE_FLAG,
    STATE_MAX_BYTES,
    build_state,
)
from products.business_knowledge.backend.models import KnowledgeDocument, SafetyVerdict
from products.ml_inference.backend.facade.contracts import (
    MAX_OPTIONS_PER_QUESTION,
    ChoiceAnswer,
    DecisionGatewayError,
    DecisionGatewayUnreachableError,
    DecisionResult,
    NoulAnswer,
)

DECIDE = "products.business_knowledge.backend.magic_eight_ball.decision_api.decide_unchecked"
EMBED = "posthog.api.embedding_worker.generate_embedding"


def _chunk(content: str, *, source_name: str = "Docs") -> logic.KnowledgeSearchResult:
    return logic.KnowledgeSearchResult(
        chunk_id=uuid4(),
        source_id=uuid4(),
        source_name=source_name,
        source_type="text",
        document_id=uuid4(),
        document_title=source_name,
        heading_path="",
        ordinal=0,
        content=content,
    )


def _decision(choice: str, confidence: float = 0.8) -> DecisionResult:
    return DecisionResult(
        model="jevk5-fp8-0.2",
        answers={ANSWER_QUESTION_ID: ChoiceAnswer(choice=choice, confidence=confidence, probabilities={choice: 0.8})},
        input_tokens=120,
    )


class TestBuildState(SimpleTestCase):
    def test_answers_fit_the_decision_model_option_limit(self) -> None:
        assert len(EIGHT_BALL_ANSWERS) <= MAX_OPTIONS_PER_QUESTION

    def test_keeps_rank_order_and_stays_under_the_byte_cap(self) -> None:
        chunks = [_chunk(f"chunk {i} " + "x" * 1500) for i in range(10)]

        state, used = build_state("Will it ship?", chunks)

        assert len(json.dumps(state, ensure_ascii=False).encode()) <= STATE_MAX_BYTES
        assert 0 < len(used) < len(chunks)
        assert used == chunks[: len(used)]

    def test_an_oversized_chunk_does_not_crowd_out_smaller_ones(self) -> None:
        huge, small = _chunk("x" * (STATE_MAX_BYTES * 2)), _chunk("refunds within 30 days")

        _, used = build_state("Do we refund?", [huge, small])

        assert used == [small]

    def test_one_document_does_not_crowd_out_lower_ranked_documents(self) -> None:
        top_document_id = uuid4()
        top = [replace(_chunk("x" * 2500), document_id=top_document_id, ordinal=i) for i in range(3)]
        other = _chunk("refunds within 30 days")

        _, used = build_state("Do we refund?", [*top, other])

        assert used[:2] == [top[0], other]


@patch("posthoganalytics.feature_enabled", return_value=True)
@patch(EMBED, side_effect=Exception("unavailable"))
class TestEightBallAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        decisions_enabled = patch(
            "products.business_knowledge.backend.magic_eight_ball.decision_api.decisions_enabled", return_value=True
        )
        decisions_enabled.start()
        self.addCleanup(decisions_enabled.stop)
        self.organization.is_ai_data_processing_approved = True
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        self.url = f"/api/projects/{self.team.id}/business_knowledge/documents/eight_ball/"
        self.source = logic.create_text_source(
            team_id=self.team.id,
            created_by_id=self.user.id,
            name="Pricing",
            text="Our pricing is usage based, and the free tier covers a million events a month.",
        )
        KnowledgeDocument.objects.unscoped().filter(source_id=self.source.id).update(safety_verdict=SafetyVerdict.SAFE)

    def test_answers_from_business_knowledge(self, _embed, _ff) -> None:
        with patch(DECIDE, return_value=_decision("Outlook good")) as decide:
            response = self.client.post(self.url, {"question": "Is our pricing usage based?"}, format="json")

        assert response.status_code == status.HTTP_200_OK, response.content
        body = response.json()
        assert body["answer"] == "Outlook good"
        assert body["confidence"] == 0.8
        assert [source["source_id"] for source in body["sources"]] == [str(self.source.id)]
        request = decide.call_args.args[0]
        assert request.team_id == self.team.id
        assert request.state["question"] == "Is our pricing usage based?"
        assert "usage based" in request.state["business_knowledge"][0]["text"]

    @override_settings(DEBUG=False)
    def test_rollout_flag_off_does_not_search(self, _embed, feature_enabled) -> None:
        feature_enabled.side_effect = lambda flag, *_args, **_kwargs: flag != MAGIC_EIGHT_BALL_FEATURE_FLAG
        with (
            patch("products.business_knowledge.backend.magic_eight_ball.logic.search_knowledge_for_team") as search,
            patch(DECIDE) as decide,
        ):
            response = self.client.post(self.url, {"question": "Will it ship?"}, format="json")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        search.assert_not_called()
        decide.assert_not_called()

    def test_answers_with_no_matching_knowledge(self, _embed, _ff) -> None:
        with (
            patch(
                "products.business_knowledge.backend.magic_eight_ball.logic.search_knowledge_for_team", return_value=[]
            ),
            patch(
                "products.business_knowledge.backend.magic_eight_ball.decision_api.decisions_enabled", return_value=True
            ),
            patch(DECIDE) as decide,
        ):
            response = self.client.post(self.url, {"question": "Will the kraken wake?"}, format="json")

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.json() == {"answer": "Cannot predict now", "confidence": 0.0, "sources": []}
        decide.assert_not_called()

    def test_checks_decision_enrollment_before_search(self, _embed, _ff) -> None:
        with (
            patch("products.business_knowledge.backend.magic_eight_ball.logic.search_knowledge_for_team") as search,
            patch(
                "products.business_knowledge.backend.magic_eight_ball.decision_api.decisions_enabled",
                return_value=False,
            ),
            patch(DECIDE) as decide,
        ):
            response = self.client.post(self.url, {"question": "Will it ship?"}, format="json")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        search.assert_not_called()
        decide.assert_not_called()

    def test_requires_ai_processing_approval_before_search(self, _embed, _ff) -> None:
        self.organization.is_ai_data_processing_approved = False
        self.organization.save(update_fields=["is_ai_data_processing_approved"])

        with (
            patch("products.business_knowledge.backend.magic_eight_ball.logic.search_knowledge_for_team") as search,
            patch(DECIDE) as decide,
        ):
            response = self.client.post(self.url, {"question": "Is our pricing usage based?"}, format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert b"million events" not in response.content
        search.assert_not_called()
        decide.assert_not_called()
        _embed.assert_not_called()

    def test_attributes_each_used_document(self, _embed, _ff) -> None:
        first = _chunk("usage based")
        chunks = [first, replace(first, chunk_id=uuid4())]
        chunks += [replace(first, document_id=uuid4(), document_title=f"Document {index}") for index in range(4)]

        with (
            patch(
                "products.business_knowledge.backend.magic_eight_ball.logic.search_knowledge_for_team",
                return_value=chunks,
            ),
            patch(DECIDE, return_value=_decision("Yes")),
        ):
            response = self.client.post(self.url, {"question": "Is our pricing usage based?"}, format="json")

        assert response.status_code == status.HTTP_200_OK, response.content
        assert [source["document_title"] for source in response.json()["sources"]] == [
            "Docs",
            "Document 0",
            "Document 1",
            "Document 2",
            "Document 3",
        ]
        assert all(source["source_id"] == str(first.source_id) for source in response.json()["sources"])

    def test_blank_question_is_rejected(self, _embed, _ff) -> None:
        with patch(DECIDE) as decide:
            response = self.client.post(self.url, {"question": "   "}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        decide.assert_not_called()

    @parameterized.expand(
        [
            ("gateway_error", DecisionGatewayError(500, "free tier covers a million events"), None),
            ("unreachable", DecisionGatewayUnreachableError(), None),
            ("gateway_not_configured", GatewayNotConfiguredError("free tier covers a million events"), None),
            ("unknown_choice", None, _decision("Maybe")),
            ("negative_confidence", None, _decision("Yes", -0.1)),
            ("high_confidence", None, _decision("Yes", 1.1)),
            ("nan_confidence", None, _decision("Yes", float("nan"))),
            ("infinite_confidence", None, _decision("Yes", float("inf"))),
            (
                "wrong_answer_type",
                None,
                DecisionResult(model="m", answers={ANSWER_QUESTION_ID: NoulAnswer(probability=0.5)}, input_tokens=1),
            ),
        ]
    )
    def test_unavailable_without_leaking_knowledge(self, _embed, _ff, _name, error, result) -> None:
        with patch(DECIDE, side_effect=error, return_value=result):
            response = self.client.post(self.url, {"question": "Is our pricing usage based?"}, format="json")

        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert b"million events" not in response.content

    def test_api_key_cannot_ask_the_magic_eight_ball(self, _embed, _ff) -> None:
        key = self.create_personal_api_key_with_scopes(["business_knowledge:read"])
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {key}")

        with patch(DECIDE) as decide:
            response = self.client.post(self.url, {"question": "Is our pricing usage based?"}, format="json")

        assert response.status_code == status.HTTP_403_FORBIDDEN
        decide.assert_not_called()

    def test_session_requests_are_rate_limited(self, _embed, _ff) -> None:
        with (
            patch("products.business_knowledge.backend.api.views._EightBallBurstRateThrottle.rate", "2/minute"),
            patch("products.business_knowledge.backend.api.views.magic_eight_ball.ask") as ask,
        ):
            first = self.client.post(self.url, {"question": "Will it ship?"}, format="json")
            second = self.client.post(self.url, {"question": "Will it ship?"}, format="json")
            third = self.client.post(self.url, {"question": "Will it ship?"}, format="json")

        assert first.status_code == status.HTTP_200_OK
        assert second.status_code == status.HTTP_200_OK
        assert third.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert ask.call_count == 2
