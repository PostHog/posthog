"""Wire types for the System One API, ``POST /v1/systemone``, shared by every server that speaks it.

A System One model such as Jev answers typed questions about a ``state`` and returns judgments
rather than text. A noul question returns the probability that a yes/no statement holds. A choice
question picks one option from the criteria the caller supplies, with a probability for every
option. Score questions exist too and stay unwired until a caller needs one, so the request body
remains a checked shape.

Keep user text in ``state`` and refer to it from the instructions by name. Never interpolate it
into ``instructions``, so user text cannot become an instruction.

TypeSafe (``posthog.egress.typesafe``) and the Go ai-gateway both serve this API. Callers pick one
through ``posthog.llm.system_one_client.build_system_one_client``.
"""

import math
from collections.abc import Mapping, Sequence
from typing import cast

from posthog.dataclasses import frozen

SYSTEM_ONE_PATH = "/v1/systemone"

# The most options a System One server takes in one choice question. A model can take fewer.
MAX_CHOICE_OPTIONS = 255

type JsonValue = str | int | float | bool | None | Mapping[str, JsonValue] | Sequence[JsonValue]


class SystemOneNotConfigured(Exception):
    """No System One server is configured on this instance, so no call was made. Self-hosted
    deployments run without one, so callers must treat this as a normal degraded path."""


class SystemOneRequestFailed(Exception):
    """A System One server was reached but did not return a usable answer (HTTP error, or a body that
    does not match the documented shape). ``status_code`` is set for an HTTP error, so a caller can
    defer a 429 or 529 and drop the rest."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@frozen
class NoulQuestion:
    """A yes/no question. ``criteria_true`` and ``criteria_false`` optionally describe what each answer means."""

    instructions: JsonValue
    criteria_true: JsonValue = None
    criteria_false: JsonValue = None

    def to_json(self) -> dict[str, JsonValue]:
        body: dict[str, JsonValue] = {"type": "noul", "instructions": self.instructions}
        criteria = {
            key: value
            for key, value in (("true", self.criteria_true), ("false", self.criteria_false))
            if value is not None
        }
        if criteria:
            body["criteria"] = criteria
        return body


@frozen
class ChoiceQuestion:
    """A pick of one option. ``criteria`` maps each option to its description, or to ``None`` when
    the option name is clear on its own."""

    instructions: JsonValue
    criteria: Mapping[str, JsonValue]

    def __post_init__(self) -> None:
        if not 1 <= len(self.criteria) <= MAX_CHOICE_OPTIONS:
            raise ValueError(f"A choice question needs between 1 and {MAX_CHOICE_OPTIONS} options")

    def to_json(self) -> dict[str, JsonValue]:
        return {"type": "choice", "instructions": self.instructions, "criteria": dict(self.criteria)}


type Question = NoulQuestion | ChoiceQuestion


@frozen
class NoulAnswer:
    probability: float


@frozen
class ChoiceAnswer:
    choice: str
    confidence: float
    probabilities: Mapping[str, float]


type Answer = NoulAnswer | ChoiceAnswer


@frozen
class SystemOneResult:
    """The answers to one request, keyed by the question ids the caller chose. ``model`` is the
    versioned id that answered, also when the request named an alias."""

    model: str
    answers: Mapping[str, Answer]
    input_tokens: int | None


def _as_mapping(value: object) -> Mapping[str, object] | None:
    # An isinstance check cannot narrow the key type, but these mappings come from a parsed JSON
    # body, where every key is a string.
    return cast(Mapping[str, object], value) if isinstance(value, Mapping) else None


def _as_probability(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    try:
        probability = float(value)
    except OverflowError:
        # JSON integers have no size limit, and one past the float range cannot be a probability.
        return None
    if not math.isfinite(probability) or not 0 <= probability <= 1:
        return None
    return probability


def _parse_answer(question_id: str, question: Question, raw: object) -> Answer:
    answer = _as_mapping(raw)
    if answer is None:
        raise SystemOneRequestFailed(f"The System One server returned no answer for {question_id!r}")

    if isinstance(question, NoulQuestion):
        probability = _as_probability(answer.get("noul"))
        # A server can leave out `type`, because the question already says which answer it expects.
        if answer.get("type", "noul") != "noul" or probability is None:
            raise SystemOneRequestFailed(f"The System One server returned a malformed noul for {question_id!r}")
        return NoulAnswer(probability=probability)

    choice = answer.get("choice")
    confidence = _as_probability(answer.get("confidence"))
    if answer.get("type", "choice") != "choice" or not isinstance(choice, str) or choice not in question.criteria:
        raise SystemOneRequestFailed(f"The System One server returned a malformed choice for {question_id!r}")
    if confidence is None:
        raise SystemOneRequestFailed(f"The System One server returned a malformed confidence for {question_id!r}")
    raw_probabilities = _as_mapping(answer.get("probabilities")) or {}
    probabilities = {option: _as_probability(raw_probabilities.get(option)) for option in question.criteria}
    complete = {option: probability for option, probability in probabilities.items() if probability is not None}
    if len(complete) != len(question.criteria):
        raise SystemOneRequestFailed(f"The System One server returned incomplete probabilities for {question_id!r}")
    return ChoiceAnswer(choice=choice, confidence=confidence, probabilities=complete)


def build_system_one_body(
    *, state: JsonValue, questions: Mapping[str, Question], model: str | None
) -> dict[str, JsonValue]:
    """The System One request body. ``model`` is left out when ``None``, so the server picks its default."""
    body: dict[str, JsonValue] = {} if model is None else {"model": model}
    body["state"] = state
    body["questions"] = {question_id: question.to_json() for question_id, question in questions.items()}
    return body


def parse_system_one_response(payload: object, questions: Mapping[str, Question]) -> SystemOneResult:
    """Validate a parsed System One JSON body against the questions that were asked.

    Raises :class:`SystemOneRequestFailed` unless the body holds a model id and a complete,
    well-formed answer to every question.
    """
    body = _as_mapping(payload)
    raw_answers = _as_mapping(body.get("answers")) if body is not None else None
    if body is None or raw_answers is None:
        raise SystemOneRequestFailed("The System One server returned no answers")
    answered_model = body.get("model")
    if not isinstance(answered_model, str) or not answered_model:
        raise SystemOneRequestFailed("The System One server returned no model")

    usage = _as_mapping(body.get("usage")) or {}
    input_tokens = usage.get("input_tokens")
    return SystemOneResult(
        model=answered_model,
        answers={
            question_id: _parse_answer(question_id, question, raw_answers.get(question_id))
            for question_id, question in questions.items()
        },
        input_tokens=input_tokens if isinstance(input_tokens, int) and not isinstance(input_tokens, bool) else None,
    )
