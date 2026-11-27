"""Ask Jev, PostHog's decision model, the yes/no and pick-one questions of AI visibility setup.

Jev picks among options the caller extracts; it writes no text. Every question about user or third-party
text keeps that text in `state` and refers to it by key from the instructions, so it cannot act as an instruction.

The model runs on a GPU pool every product shares, so a job sends few requests at once and every worker
pauses when one request is throttled.
"""

from __future__ import annotations

import time
import threading
from collections.abc import Callable, Mapping, Sequence
from typing import TypeVar

from django.conf import settings

import structlog

from posthog.dataclasses import frozen
from posthog.llm.gateway_client import team_distinct_id
from posthog.llm.system_one import (
    Answer,
    ChoiceAnswer,
    ChoiceQuestion,
    JsonValue,
    NoulAnswer,
    NoulQuestion,
    Question,
    SystemOneNotConfigured,
    SystemOneRequestFailed,
)
from posthog.llm.system_one_client import GATEWAY_MAX_CHOICE_OPTIONS, build_system_one_client

from products.aeo.backend.engines import SharedBackoff

logger = structlog.get_logger(__name__)

AI_PRODUCT = "aeo"
# The model reads every question against the whole state, so a request stays small: fewer questions than the
# gateway's cap, each over a short text.
QUESTIONS_PER_REQUEST = 16
STATE_TEXT_CHARS = 300
REQUEST_TIMEOUT_SECONDS = 30.0
MAX_ATTEMPTS = 3
RETRY_BASE_SECONDS = 2
RETRY_MAX_SECONDS = 30
THROTTLED_STATUS_CODES = frozenset({429, 529})
RETRYABLE_STATUS_CODES = THROTTLED_STATUS_CODES | {500, 502, 503, 504}

T = TypeVar("T")


class DecisionError(Exception):
    """No usable answer came back. Callers fall back to the path that does not need the model."""


@frozen
class DecisionUsage:
    """What one batch of questions cost: how many requests ran, how many were throttled, and the tokens read."""

    requests: int = 0
    throttled: int = 0
    failed: int = 0
    input_tokens: int = 0
    seconds: float = 0.0


class _Throttle:
    """Caps the requests a process keeps in flight at the decision model, and shares one backoff among them."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._slots: threading.BoundedSemaphore | None = None
        self._size = 0
        self.backoff = SharedBackoff()

    def slots(self) -> threading.BoundedSemaphore:
        size = max(1, settings.AEO_DECISION_CONCURRENCY)
        with self._lock:
            if self._slots is None or size != self._size:
                self._slots = threading.BoundedSemaphore(size)
                self._size = size
            return self._slots


THROTTLE = _Throttle()


def _retry_delay(attempt: int) -> float:
    return min(RETRY_BASE_SECONDS * 2**attempt, RETRY_MAX_SECONDS)


def configured() -> bool:
    try:
        build_system_one_client(model=settings.AEO_DECISION_MODEL, ai_product=AI_PRODUCT)
    except SystemOneNotConfigured:
        return False
    return True


def _clip(text: str) -> str:
    return " ".join(text.split())[:STATE_TEXT_CHARS]


def ask(
    *,
    team_id: int,
    feature: str,
    state: Mapping[str, JsonValue],
    questions: Mapping[str, Question],
    usage: list[DecisionUsage] | None = None,
) -> Mapping[str, Answer]:
    """Answers to every question, in one or more requests. Raises DecisionError when a request has no usable
    answer after its retries, or when no decision model is configured."""
    try:
        client = build_system_one_client(
            model=settings.AEO_DECISION_MODEL,
            ai_product=AI_PRODUCT,
            team_id=team_id,
            distinct_id=team_distinct_id(team_id),
            properties={"aeo_feature": feature},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except SystemOneNotConfigured as error:
        raise DecisionError("No decision model is configured") from error
    answers: dict[str, Answer] = {}
    ids = list(questions)
    requests = throttled = failed = input_tokens = 0
    started = time.monotonic()
    try:
        for start in range(0, len(ids), QUESTIONS_PER_REQUEST):
            batch = {question_id: questions[question_id] for question_id in ids[start : start + QUESTIONS_PER_REQUEST]}
            for attempt in range(MAX_ATTEMPTS):
                THROTTLE.backoff.wait()
                requests += 1
                try:
                    with THROTTLE.slots():
                        result = client.decide(state=dict(state), questions=batch)
                except SystemOneRequestFailed as error:
                    failed += 1
                    status = error.status_code
                    if status in THROTTLED_STATUS_CODES:
                        throttled += 1
                    if status not in RETRYABLE_STATUS_CODES or attempt == MAX_ATTEMPTS - 1:
                        logger.warning("aeo_decision_failed", team_id=team_id, feature=feature, status=status)
                        raise DecisionError(str(error)) from error
                    THROTTLE.backoff.pause(_retry_delay(attempt))
                    continue
                answers.update(result.answers)
                input_tokens += result.input_tokens or 0
                break
    finally:
        if usage is not None:
            usage.append(
                DecisionUsage(
                    requests=requests,
                    throttled=throttled,
                    failed=failed,
                    input_tokens=input_tokens,
                    seconds=time.monotonic() - started,
                )
            )
    return answers


def yes_probabilities(
    *,
    team_id: int,
    feature: str,
    context: Mapping[str, JsonValue],
    items: Sequence[str],
    item_key: str,
    question: str,
    criteria_true: str,
    criteria_false: str,
    usage: list[DecisionUsage] | None = None,
) -> list[float]:
    """The probability that `question` holds for each item, in the items' order. `question` names the item as
    `{key}`, which resolves to `{item_key}.iN` in the state, next to the caller's `context`."""
    probabilities: list[float] = []
    for start in range(0, len(items), QUESTIONS_PER_REQUEST):
        chunk = items[start : start + QUESTIONS_PER_REQUEST]
        keys = [f"i{index}" for index in range(len(chunk))]
        state: dict[str, JsonValue] = {**context, item_key: dict(zip(keys, (_clip(item) for item in chunk)))}
        questions = {
            key: NoulQuestion(
                instructions=question.format(key=f"{item_key}.{key}"),
                criteria_true=criteria_true,
                criteria_false=criteria_false,
            )
            for key in keys
        }
        answers = ask(team_id=team_id, feature=feature, state=state, questions=questions, usage=usage)
        for key in keys:
            answer = answers[key]
            # A refusal counts as a no: the item is dropped rather than kept on a guess.
            probabilities.append(answer.probability if isinstance(answer, NoulAnswer) else 0.0)
    return probabilities


def pick_one(
    *,
    team_id: int,
    feature: str,
    context: Mapping[str, JsonValue],
    items: Sequence[str],
    item_key: str,
    question: str,
    options: Mapping[str, str | None],
    usage: list[DecisionUsage] | None = None,
) -> list[ChoiceAnswer | None]:
    """One option for each item, in the items' order, or None where the model refused. Raises ValueError when
    there are more options than the gateway takes in one question."""
    if len(options) > GATEWAY_MAX_CHOICE_OPTIONS:
        raise ValueError(f"A choice takes at most {GATEWAY_MAX_CHOICE_OPTIONS} options")
    choices: list[ChoiceAnswer | None] = []
    for start in range(0, len(items), QUESTIONS_PER_REQUEST):
        chunk = items[start : start + QUESTIONS_PER_REQUEST]
        keys = [f"i{index}" for index in range(len(chunk))]
        state: dict[str, JsonValue] = {**context, item_key: dict(zip(keys, (_clip(item) for item in chunk)))}
        questions = {
            key: ChoiceQuestion(instructions=question.format(key=f"{item_key}.{key}"), criteria=dict(options))
            for key in keys
        }
        answers = ask(team_id=team_id, feature=feature, state=state, questions=questions, usage=usage)
        for key in keys:
            answer = answers[key]
            choices.append(answer if isinstance(answer, ChoiceAnswer) else None)
    return choices


def with_fallback(run: Callable[[], T], fallback: Callable[[], T], *, team_id: int, feature: str) -> T:
    """`run()`, or `fallback()` when the decision model gives no usable answer, so a GPU outage degrades a
    setup step to the path it had before instead of failing it."""
    try:
        return run()
    except DecisionError:
        logger.warning("aeo_decision_fallback", team_id=team_id, feature=feature)
        return fallback()
