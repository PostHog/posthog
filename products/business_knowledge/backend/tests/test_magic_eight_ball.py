import json
from uuid import uuid4

from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from products.business_knowledge.backend import logic
from products.business_knowledge.backend.magic_eight_ball import (
    ANSWER_QUESTION_ID,
    EIGHT_BALL_ANSWERS,
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
    DecisionsDisabledError,
    NoulAnswer,
)

DECIDE = "products.business_knowledge.backend.magic_eight_ball.decision_api.decide"
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


def _decision(choice: str) -> DecisionResult:
    return DecisionResult(
        model="jevk5-fp8-0.2",
        answers={ANSWER_QUESTION_ID: ChoiceAnswer(choice=choice, confidence=0.8, probabilities={choice: 0.8})},
        input_tokens=120,
    )


class TestBuildState(BaseTest):
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


@patch("posthoganalytics.feature_enabled", return_value=True)
@patch(EMBED, side_effect=Exception("unavailable"))
class TestEightBallAPI(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
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

    def test_answers_with_no_matching_knowledge(self, _embed, _ff) -> None:
        with patch(DECIDE, return_value=_decision("Cannot predict now")) as decide:
            response = self.client.post(self.url, {"question": "Will the kraken wake?"}, format="json")

        assert response.status_code == status.HTTP_200_OK, response.content
        assert response.json()["sources"] == []
        assert decide.call_args.args[0].state["business_knowledge"] == []

    def test_blank_question_is_rejected(self, _embed, _ff) -> None:
        with patch(DECIDE) as decide:
            response = self.client.post(self.url, {"question": "   "}, format="json")

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        decide.assert_not_called()

    def test_not_found_when_decisions_are_not_enabled(self, _embed, _ff) -> None:
        with patch(DECIDE, side_effect=DecisionsDisabledError(self.team.id)):
            response = self.client.post(self.url, {"question": "Is our pricing usage based?"}, format="json")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    @parameterized.expand(
        [
            ("gateway_error", DecisionGatewayError(500, "free tier covers a million events"), None),
            ("unreachable", DecisionGatewayUnreachableError(), None),
            ("unknown_choice", None, _decision("Maybe")),
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

    def test_read_scope_is_enough(self, _embed, _ff) -> None:
        key = self.create_personal_api_key_with_scopes(["business_knowledge:read"])
        self.client.logout()
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {key}")

        with patch(DECIDE, return_value=_decision("Yes")):
            response = self.client.post(self.url, {"question": "Is our pricing usage based?"}, format="json")

        assert response.status_code == status.HTTP_200_OK, response.content
