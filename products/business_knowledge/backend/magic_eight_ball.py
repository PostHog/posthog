"""
The magic 8 ball: answers a product question from the team's business knowledge.

Business knowledge search finds what the team has written about the question, and the decision
model (through the ml_inference facade) picks which of the ball's answers that knowledge supports.
"""

import json
import math
from dataclasses import dataclass
from uuid import UUID, uuid4

from django.core.exceptions import PermissionDenied

from posthog.models.team import Team

from products.ml_inference.backend.facade import api as decision_api
from products.ml_inference.backend.facade.contracts import (
    ChoiceAnswer,
    DecisionQuestion,
    DecisionRequest,
    DecisionsDisabledError,
    JsonValue,
)
from products.ml_inference.backend.facade.enums import DecisionQuestionType

from . import logic

ANSWER_QUESTION_ID = "answer"
SEARCH_LIMIT = 8
# Jev's deployed context is 8,192 tokens and a UTF-8 byte can be one token, so this leaves room for the framing.
STATE_MAX_BYTES = 6 * 1024

INSTRUCTIONS = (
    "You are a Magic 8 Ball for this company. `question` is a product question someone asked you. "
    "`business_knowledge` is what the company has written about itself, most relevant first. "
    "Pick the answer the business knowledge best supports. "
    "When the business knowledge does not bear on the question, pick one of the unsure answers."
)

# The decision model answers with one letter per option, so a question takes at most 16 options.
# The classic ball has 20 answers; these 16 keep an 8 yes, 4 unsure, 4 no split.
EIGHT_BALL_ANSWERS: dict[str, str] = {
    "It is certain": "the knowledge clearly and fully says yes",
    "Without a doubt": "the knowledge confidently says yes",
    "Yes definitely": "the knowledge says yes",
    "As I see it, yes": "the knowledge says yes, with some hedging",
    "Most likely": "the knowledge suggests yes",
    "Outlook good": "the knowledge makes it look promising",
    "Yes": "a plain yes",
    "Signs point to yes": "the knowledge leans yes",
    "Reply hazy, try again": "the question is too vague to answer",
    "Ask again later": "the knowledge says it is not decided yet",
    "Better not tell you now": "the knowledge touches on it but does not settle it",
    "Cannot predict now": "the knowledge says nothing about it",
    "Don't count on it": "the knowledge suggests no",
    "My reply is no": "the knowledge says no",
    "Outlook not so good": "the knowledge makes it look unpromising",
    "Very doubtful": "the knowledge makes it very unlikely",
}


class InvalidEightBallAnswer(Exception):
    """The decision model answered, but not with one of the ball's answers."""


@dataclass(frozen=True)
class EightBallSource:
    source_id: UUID
    source_name: str
    document_title: str


@dataclass(frozen=True)
class EightBallAnswer:
    answer: str
    confidence: float
    sources: list[EightBallSource]


def build_state(
    question: str, chunks: list[logic.KnowledgeSearchResult]
) -> tuple[dict[str, JsonValue], list[logic.KnowledgeSearchResult]]:
    """Pack the highest ranked chunks that fit under STATE_MAX_BYTES, and return the chunks that made it in."""
    knowledge: list[JsonValue] = []
    used: list[logic.KnowledgeSearchResult] = []
    for chunk in chunks:
        entry: dict[str, JsonValue] = {
            "source": chunk.source_name,
            "document": chunk.document_title,
            "section": chunk.heading_path,
            "text": chunk.content,
        }
        candidate = {"question": question, "business_knowledge": [*knowledge, entry]}
        # Skip rather than stop, so one oversized chunk does not crowd out smaller ones ranked below it.
        if len(json.dumps(candidate, ensure_ascii=False).encode()) > STATE_MAX_BYTES:
            continue
        knowledge.append(entry)
        used.append(chunk)
    return {"question": question, "business_knowledge": knowledge}, used


def _sources(chunks: list[logic.KnowledgeSearchResult]) -> list[EightBallSource]:
    sources: dict[UUID, EightBallSource] = {}
    for chunk in chunks:
        if chunk.document_id not in sources:
            sources[chunk.document_id] = EightBallSource(
                source_id=chunk.source_id,
                source_name=chunk.source_name,
                document_title=chunk.document_title,
            )
    return list(sources.values())


def ask(team: Team, question: str) -> EightBallAnswer:
    """
    Raises the facade's DecisionsDisabledError when the team is not enrolled in decisions, and its
    gateway errors, or InvalidEightBallAnswer, when the model gives no usable answer.
    """
    if not team.organization.is_ai_data_processing_approved:
        raise PermissionDenied("AI data processing is not approved for this organization.")

    chunks = logic.search_knowledge_for_team(team, question, limit=SEARCH_LIMIT)
    state, used = build_state(question, chunks)
    if not used:
        if not decision_api.decisions_enabled(team.id):
            raise DecisionsDisabledError(team.id)
        return EightBallAnswer(answer="Cannot predict now", confidence=0, sources=[])

    result = decision_api.decide(
        DecisionRequest(
            team_id=team.id,
            state=state,
            questions={
                ANSWER_QUESTION_ID: DecisionQuestion(
                    type=DecisionQuestionType.CHOICE,
                    instructions=INSTRUCTIONS,
                    criteria=EIGHT_BALL_ANSWERS,
                )
            },
            ai_product="business_knowledge",
            trace_id=str(uuid4()),
            properties={"feature": "magic_eight_ball"},
        )
    )
    answer = result.answers.get(ANSWER_QUESTION_ID)
    if (
        not isinstance(answer, ChoiceAnswer)
        or answer.choice not in EIGHT_BALL_ANSWERS
        or not isinstance(answer.confidence, (int, float))
        or not math.isfinite(answer.confidence)
        or not 0 <= answer.confidence <= 1
    ):
        raise InvalidEightBallAnswer()
    return EightBallAnswer(answer=answer.choice, confidence=answer.confidence, sources=_sources(used))
