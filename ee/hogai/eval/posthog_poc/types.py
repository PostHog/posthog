from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any, Generic, Literal, TypeVar

InputT = TypeVar("InputT")
ExpectedT = TypeVar("ExpectedT")


@dataclass(frozen=True)
class EvalCase(Generic[InputT, ExpectedT]):
    id: str
    name: str
    input: InputT
    expected: ExpectedT
    dataset_item_id: str | None = None


@dataclass(frozen=True)
class MetricOutcome:
    status: Literal["ok", "not_applicable", "skipped", "error"]
    score: float | None
    reasoning: str | None = None
    trace_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class EvalRunContext:
    distinct_id: str
    experiment_id: str
    experiment_name: str
    evaluation_type: str
    dataset_id: str | None
    posthog_client: Any


MetricScorer = Callable[[EvalCase[Any, Any], Any, EvalRunContext], Awaitable[MetricOutcome]]


@dataclass(frozen=True)
class EvalMetric:
    name: str
    version: str
    result_type: Literal["binary", "numeric"]
    score_min: float | None
    score_max: float | None
    scorer: MetricScorer


TaskRunner = Callable[[Any], Awaitable[Any]]


@dataclass(frozen=True)
class EvalSuite(Generic[InputT, ExpectedT]):
    experiment_name: str
    task: TaskRunner
    cases: Sequence[EvalCase[InputT, ExpectedT]]
    metrics: Sequence[EvalMetric]
    dataset_id: str | None = None
    evaluation_type: str = "offline"
