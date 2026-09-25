"""Typed client for TypeSafe's System One endpoint, ``POST /v1/systemone``.

A System One model such as Jev answers typed questions about a ``state`` and returns judgments
rather than text. A noul question returns the probability that a yes/no statement holds. A choice
question picks one option from the criteria the caller supplies, with a probability for every
option. Score questions exist too and stay unwired until a caller needs one, so the request body
remains a checked shape.

Keep user text in ``state`` and refer to it from the instructions by name. Never interpolate it
into ``instructions``, so user text cannot become an instruction.

USAGE POLICY. TypeSafe is approved for experiments only. Read "Usage policy" in this package's
README.md before you add a caller. In short: gate every caller behind a feature flag that reaches
PostHog staff only, and send no customer data. A launch that sends customer data needs an explicit
opt-in from each customer and sign-off from leadership first.
"""

import math
from collections.abc import Mapping, Sequence
from typing import cast

from django.conf import settings

from posthog.dataclasses import frozen
from posthog.egress.limiter.policies import Priority
from posthog.egress.typesafe.transport import DEFAULT_TIMEOUT, typesafe_request

TYPESAFE_API_BASE = "https://api.typesafe.ai"
SYSTEM_ONE_ENDPOINT = "/v1/systemone"

# The alias moves to each new release. A caller that tunes thresholds against one version pins that
# version's id instead, so a release cannot shift its answers without a code change.
JEV_LATEST = "jev-latest"

# TypeSafe rejects a choice question with more options than this.
MAX_CHOICE_OPTIONS = 255

type JsonValue = str | int | float | bool | None | Mapping[str, JsonValue] | Sequence[JsonValue]


class TypeSafeNotConfigured(Exception):
    """No TypeSafe API key is configured on this instance, so no call was made. Self-hosted
    deployments run without one, so callers must treat this as a normal degraded path."""


class TypeSafeRequestFailed(Exception):
    """TypeSafe was reached but did not return a usable answer (HTTP error, or a body that does not
    match the documented shape). ``status_code`` is set for an HTTP error, so a caller can defer a
    429 or 529 and drop the rest."""

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
        raise TypeSafeRequestFailed(f"TypeSafe returned no answer for {question_id!r}")

    if isinstance(question, NoulQuestion):
        probability = _as_probability(answer.get("noul"))
        if answer.get("type") != "noul" or probability is None:
            raise TypeSafeRequestFailed(f"TypeSafe returned a malformed noul for {question_id!r}")
        return NoulAnswer(probability=probability)

    choice = answer.get("choice")
    confidence = _as_probability(answer.get("confidence"))
    if answer.get("type") != "choice" or not isinstance(choice, str) or choice not in question.criteria:
        raise TypeSafeRequestFailed(f"TypeSafe returned a malformed choice for {question_id!r}")
    if confidence is None:
        raise TypeSafeRequestFailed(f"TypeSafe returned a malformed confidence for {question_id!r}")
    raw_probabilities = _as_mapping(answer.get("probabilities")) or {}
    probabilities = {option: _as_probability(raw_probabilities.get(option)) for option in question.criteria}
    complete = {option: probability for option, probability in probabilities.items() if probability is not None}
    if len(complete) != len(question.criteria):
        raise TypeSafeRequestFailed(f"TypeSafe returned incomplete probabilities for {question_id!r}")
    return ChoiceAnswer(choice=choice, confidence=confidence, probabilities=complete)


def system_one(
    *,
    state: JsonValue,
    questions: Mapping[str, Question],
    source: str,
    model: str = JEV_LATEST,
    priority: Priority = Priority.NORMAL,
    timeout: float | tuple[float, float] = DEFAULT_TIMEOUT,
) -> SystemOneResult:
    """Evaluate ``state`` against every question in one call. TypeSafe answers the questions in
    parallel, so a caller asks everything it needs in one request.

    Raises :class:`TypeSafeNotConfigured` when the instance has no API key,
    :class:`TypeSafeRequestFailed` when TypeSafe answers with anything but a complete set of answers,
    and :class:`~posthog.egress.typesafe.transport.TypeSafeEgressBudgetExhausted` when our own egress
    budget sheds the call. Nothing retries a 429 or a 529 here, so the caller owns any retry.
    """
    if not questions:
        raise ValueError("system_one needs at least one question")
    api_key = settings.TYPESAFE_API_KEY
    if not api_key:
        raise TypeSafeNotConfigured("No TYPESAFE_API_KEY configured")

    response = typesafe_request(
        "POST",
        f"{TYPESAFE_API_BASE}{SYSTEM_ONE_ENDPOINT}",
        api_key=api_key,
        source=source,
        endpoint=SYSTEM_ONE_ENDPOINT,
        priority=priority,
        timeout=timeout,
        allow_redirects=False,
        json={
            "model": model,
            "state": state,
            "questions": {question_id: question.to_json() for question_id, question in questions.items()},
        },
    )

    if not response.ok:
        # A 422 body echoes the offending field, which can carry the state, so keep the body out of
        # the exception that gets logged.
        raise TypeSafeRequestFailed(f"TypeSafe returned HTTP {response.status_code}", status_code=response.status_code)
    try:
        payload: object = response.json()
    except ValueError as exc:
        raise TypeSafeRequestFailed("TypeSafe returned a non-JSON body") from exc

    body = _as_mapping(payload)
    raw_answers = _as_mapping(body.get("answers")) if body is not None else None
    if body is None or raw_answers is None:
        raise TypeSafeRequestFailed("TypeSafe returned no answers")
    answered_model = body.get("model")
    if not isinstance(answered_model, str) or not answered_model:
        raise TypeSafeRequestFailed("TypeSafe returned no model")

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
