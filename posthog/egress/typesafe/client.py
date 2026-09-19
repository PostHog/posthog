"""Typed client for the one TypeSafe endpoint PostHog calls: ``POST /v1/systemone``.

Jev answers typed questions about a ``state`` document. It never writes free text: a ``choice``
question picks one option from the criteria the caller supplies, and a ``noul`` question returns a
probability that a statement holds. Callers therefore build the candidates and Jev ranks them.

Two rules from Jev's documented failure modes shape every question built on this client:

1. User text lives in ``state`` and is referenced from the instructions by path. It is never
   interpolated into ``instructions``, so a person's title cannot become an instruction.
2. Instructions spell out the boundary cases, because Jev answers the question as written.
"""

import math
from collections.abc import Mapping
from typing import cast

from django.conf import settings

from posthog.dataclasses import frozen
from posthog.egress.limiter.policies import Priority
from posthog.egress.typesafe.transport import typesafe_request

TYPESAFE_API_BASE = "https://api.typesafe.ai"
SYSTEM_ONE_ENDPOINT = "/v1/systemone"

# Pinned rather than ``jev-latest`` so a model release cannot change answers under a threshold
# somebody tuned against the pinned version.
JEV_MODEL = "jev-1.13.0"

# Jev answers in well under a second. A person is waiting on the other end, so a slow answer is worth
# less than an empty field they can fill in themselves.
DEFAULT_TIMEOUT: tuple[float, float] = (3.0, 8.0)

# TypeSafe caps a choice question at 255 options.
MAX_CHOICE_OPTIONS = 255


class TypesafeNotConfigured(Exception):
    """No TypeSafe API key is configured on this instance, so no call was made."""


class TypesafeCallFailed(Exception):
    """TypeSafe was reached but did not return a usable answer (HTTP error, or a body that does not
    match the documented shape)."""


@frozen
class ChoiceQuestion:
    instructions: str
    criteria: Mapping[str, str]

    def __post_init__(self) -> None:
        if not self.criteria:
            raise ValueError("A choice question needs at least one option")
        if len(self.criteria) > MAX_CHOICE_OPTIONS:
            raise ValueError(f"A choice question takes at most {MAX_CHOICE_OPTIONS} options")


@frozen
class NoulQuestion:
    instructions: str
    true: str | None = None
    false: str | None = None


@frozen
class ChoiceAnswer:
    choice: str
    confidence: float
    probabilities: Mapping[str, float]


@frozen
class NoulAnswer:
    probability: float


@frozen
class SystemOneResult:
    model: str
    answers: Mapping[str, ChoiceAnswer | NoulAnswer]
    input_tokens: int


def _as_mapping(value: object) -> Mapping[str, object] | None:
    return cast(Mapping[str, object], value) if isinstance(value, Mapping) else None


def _as_probability(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    probability = float(value)
    if not math.isfinite(probability) or not 0 <= probability <= 1:
        return None
    return probability


def _serialize_question(question: ChoiceQuestion | NoulQuestion) -> dict[str, object]:
    if isinstance(question, ChoiceQuestion):
        return {"type": "choice", "instructions": question.instructions, "criteria": dict(question.criteria)}
    payload: dict[str, object] = {"type": "noul", "instructions": question.instructions}
    criteria = {key: text for key, text in (("true", question.true), ("false", question.false)) if text}
    if criteria:
        payload["criteria"] = criteria
    return payload


def _parse_answer(key: str, question: ChoiceQuestion | NoulQuestion, raw: object) -> ChoiceAnswer | NoulAnswer:
    answer = _as_mapping(raw)
    if answer is None:
        raise TypesafeCallFailed(f"TypeSafe returned no answer for {key!r}")
    if isinstance(question, NoulQuestion):
        probability = _as_probability(answer.get("noul"))
        if probability is None:
            raise TypesafeCallFailed(f"TypeSafe returned an invalid noul for {key!r}")
        return NoulAnswer(probability=probability)
    choice = answer.get("choice")
    if not isinstance(choice, str) or choice not in question.criteria:
        raise TypesafeCallFailed(f"TypeSafe returned an unknown option for {key!r}")
    confidence = _as_probability(answer.get("confidence"))
    if confidence is None:
        raise TypesafeCallFailed(f"TypeSafe returned an invalid confidence for {key!r}")
    probabilities: dict[str, float] = {}
    for option, value in (_as_mapping(answer.get("probabilities")) or {}).items():
        parsed = _as_probability(value)
        if option in question.criteria and parsed is not None:
            probabilities[option] = parsed
    return ChoiceAnswer(choice=choice, confidence=confidence, probabilities=probabilities)


def system_one(
    *,
    state: Mapping[str, object],
    questions: Mapping[str, ChoiceQuestion | NoulQuestion],
    source: str,
    priority: Priority = Priority.NORMAL,
    timeout: float | tuple[float, float] = DEFAULT_TIMEOUT,
) -> SystemOneResult:
    """Ask Jev every question in ``questions`` about ``state`` in one request.

    Raises :class:`TypesafeNotConfigured` when the instance has no API key,
    :class:`TypesafeCallFailed` when TypeSafe answers with anything but a usable result, and
    :class:`~posthog.egress.typesafe.transport.TypesafeEgressBudgetExhausted` when our own egress
    budget sheds the call.
    """
    if not questions:
        raise ValueError("system_one needs at least one question")
    api_key = settings.TYPESAFE_API_KEY
    if not api_key:
        raise TypesafeNotConfigured("No TYPESAFE_API_KEY configured")

    response = typesafe_request(
        "POST",
        f"{TYPESAFE_API_BASE}{SYSTEM_ONE_ENDPOINT}",
        api_key=api_key,
        source=source,
        endpoint=SYSTEM_ONE_ENDPOINT,
        priority=priority,
        timeout=timeout,
        json={
            "model": JEV_MODEL,
            "state": dict(state),
            "questions": {key: _serialize_question(question) for key, question in questions.items()},
        },
    )

    if not response.ok:
        # The body can echo the state, so keep it out of the exception that gets logged.
        raise TypesafeCallFailed(f"TypeSafe returned HTTP {response.status_code}")

    try:
        payload: object = response.json()
    except ValueError as exc:
        raise TypesafeCallFailed("TypeSafe returned a non-JSON body") from exc

    body = _as_mapping(payload)
    raw_answers = _as_mapping(body.get("answers")) if body is not None else None
    if body is None or raw_answers is None:
        raise TypesafeCallFailed("TypeSafe returned no answers")

    model = body.get("model")
    usage = _as_mapping(body.get("usage")) or {}
    input_tokens = usage.get("input_tokens")
    return SystemOneResult(
        model=model if isinstance(model, str) else JEV_MODEL,
        answers={key: _parse_answer(key, question, raw_answers.get(key)) for key, question in questions.items()},
        input_tokens=input_tokens if isinstance(input_tokens, int) and not isinstance(input_tokens, bool) else 0,
    )
