"""What a preview of an unsaved evaluation runs on, one class per target.

A unit is what one run covers: a generation, a trace or a session. Each class samples the units a live
evaluation would pick, previews them and judges one, with the same functions the live run uses.
"""

from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from typing import Any, ClassVar

from posthog.hogql import ast

from posthog.dataclasses import frozen
from posthog.models import Team, User
from posthog.temporal.ai_observability.evaluation_llm_judge import ExecuteLLMJudgeInputs, run_generation_llm_judge
from posthog.temporal.ai_observability.evaluation_types import EvaluationActivityResult
from posthog.temporal.ai_observability.run_session_evaluation import (
    ExecuteSessionEvaluationInputs,
    run_session_llm_judge,
    sample_test_sessions,
)
from posthog.temporal.ai_observability.run_trace_evaluation import (
    ExecuteTraceEvaluationInputs,
    TraceHogTestSample,
    run_trace_llm_judge,
    sample_test_traces,
)

from ...backfill_candidates import ai_events_unit_key
from ...evaluation_conditions import build_condition_filter
from ...facade import contracts
from ...models.evaluation_configs import (
    SESSION_EVAL_DEFAULT_QUIET_PERIOD_SECONDS,
    SESSION_EVAL_DEFAULT_WINDOW_SECONDS,
    SESSION_EVAL_MAX_QUIET_PERIOD_SECONDS,
    SESSION_TEST_HOG_MAX_SAMPLES,
    TRACE_EVAL_DEFAULT_WINDOW_SECONDS,
    TRACE_EVAL_MAX_WINDOW_SECONDS,
)
from .preview_queries import (
    GenerationEvent,
    UnitPreview,
    generation_io_preview,
    load_generation_events,
    load_generation_ids,
    load_unit_previews,
)

Reading = Callable[[], AbstractContextManager[None]]

DEFAULT_PREVIEW_UNITS = 5
MAX_PREVIEW_UNITS = 10


def trace_window_seconds(settle: contracts.EvaluationPreviewSettle) -> int:
    """How long after its first matching generation a trace is sampled, so its window has closed."""
    return min(settle.window_seconds or TRACE_EVAL_DEFAULT_WINDOW_SECONDS, TRACE_EVAL_MAX_WINDOW_SECONDS)


def session_quiet_period_seconds(settle: contracts.EvaluationPreviewSettle) -> int:
    """How long a session has been quiet before it is sampled: as long as the evaluation would wait for it.

    A fixed window waits its window, so the same stretch of inactivity proves the session has settled.
    """
    if settle.strategy == "fixed_window":
        waits = settle.window_seconds or SESSION_EVAL_DEFAULT_WINDOW_SECONDS
    else:
        waits = settle.quiet_period_seconds or SESSION_EVAL_DEFAULT_QUIET_PERIOD_SECONDS
    return min(waits, SESSION_EVAL_MAX_QUIET_PERIOD_SECONDS)


@frozen
class PreviewSampling:
    """Which units a preview picks: the evaluation's filters and sampling, and how long it waits to settle."""

    condition_filter: ast.Expr | None
    settle: contracts.EvaluationPreviewSettle


def preview_sampling(team: Team, scope: contracts.EvaluationPreviewScope) -> PreviewSampling:
    return PreviewSampling(
        # With the unit key, each condition set also applies the scheduler's rollout bucket, so a unit outside
        # the sampling percentage is never previewed.
        condition_filter=build_condition_filter(
            [dict(condition) for condition in scope.conditions], team, ai_events_unit_key(scope.target)
        ),
        settle=scope.settle,
    )


class PreviewUnits[Unit](ABC):
    """`Unit` is what the target's judge needs to run: an event, a trace sample or a session id."""

    target: ClassVar[contracts.EvaluationUnitKind]
    max_units: ClassVar[int] = MAX_PREVIEW_UNITS

    @abstractmethod
    def load(
        self, team: Team, user: User, sampling: PreviewSampling, count: int, sample_ids: Sequence[str] | None = None
    ) -> list[Unit]:
        """The latest settled units the sampling picks, newest first, or exactly `sample_ids`."""

    @abstractmethod
    def unit_id(self, unit: Unit) -> str: ...

    @abstractmethod
    def previews(self, team: Team, user: User, units: Sequence[Unit]) -> dict[str, UnitPreview]:
        """A preview per unit id. A unit with no generation left to preview is absent."""

    @abstractmethod
    def judge(self, evaluation: dict[str, Any], unit: Unit, user: User, reading: Reading) -> EvaluationActivityResult:
        """Grade one unit with the function a live run uses, as `user`. Nothing is emitted or saved.
        `reading` wraps the ClickHouse reads the judge makes, and not its model call."""

    def sample_ids(self, team: Team, user: User, sampling: PreviewSampling, count: int) -> list[str]:
        return [self.unit_id(unit) for unit in self.load(team, user, sampling, count)]


class GenerationUnits(PreviewUnits[GenerationEvent]):
    target = "generation"

    def load(
        self, team: Team, user: User, sampling: PreviewSampling, count: int, sample_ids: Sequence[str] | None = None
    ) -> list[GenerationEvent]:
        return load_generation_events(
            team, user, condition_filter=sampling.condition_filter, sample_count=count, sample_ids=sample_ids
        )

    def sample_ids(self, team: Team, user: User, sampling: PreviewSampling, count: int) -> list[str]:
        # Ids alone skip the payload columns, which `load` reads for every row it returns.
        return load_generation_ids(team, user, sampling.condition_filter, count)

    def unit_id(self, unit: GenerationEvent) -> str:
        return unit["uuid"]

    def previews(self, team: Team, user: User, units: Sequence[GenerationEvent]) -> dict[str, UnitPreview]:
        return {
            unit["uuid"]: UnitPreview(
                unit_id=unit["uuid"],
                trace_id=unit["properties"].get("$ai_trace_id") or None,
                timestamp=unit["timestamp"],
                io=generation_io_preview(unit),
            )
            for unit in units
        }

    def judge(
        self, evaluation: dict[str, Any], unit: GenerationEvent, user: User, reading: Reading
    ) -> EvaluationActivityResult:
        return run_generation_llm_judge(ExecuteLLMJudgeInputs(evaluation=evaluation, event_data=unit))


class _AggregateUnits[Unit](PreviewUnits[Unit]):
    """A trace or a session: many generations, previewed from the latest one."""

    def previews(self, team: Team, user: User, units: Sequence[Unit]) -> dict[str, UnitPreview]:
        unit_ids = [self.unit_id(unit) for unit in units]
        return {preview.unit_id: preview for preview in load_unit_previews(team, user, self.target, unit_ids)}


class TraceUnits(_AggregateUnits[TraceHogTestSample]):
    target = "trace"

    def load(
        self, team: Team, user: User, sampling: PreviewSampling, count: int, sample_ids: Sequence[str] | None = None
    ) -> list[TraceHogTestSample]:
        return sample_test_traces(
            team,
            sampling.condition_filter,
            count,
            window_seconds=trace_window_seconds(sampling.settle),
            user=user,
            sample_ids=sample_ids,
        )

    def unit_id(self, unit: TraceHogTestSample) -> str:
        return unit.trace_id

    def judge(
        self, evaluation: dict[str, Any], unit: TraceHogTestSample, user: User, reading: Reading
    ) -> EvaluationActivityResult:
        # No window end, like a live run, which reads the whole trace. A pinned trace's trigger is its first
        # generation, so a window from there could cut off the generation that matched the filters.
        return run_trace_llm_judge(
            ExecuteTraceEvaluationInputs(
                evaluation=evaluation,
                team_id=evaluation["team_id"],
                trace_id=unit.trace_id,
                window_start=unit.trigger_timestamp.isoformat(),
            ),
            user=user,
            reading=reading,
        )


class SessionUnits(_AggregateUnits[str]):
    target = "session"
    # Each session is a whole conversation, so a preview reads fewer of them than of traces.
    max_units = SESSION_TEST_HOG_MAX_SAMPLES

    def load(
        self, team: Team, user: User, sampling: PreviewSampling, count: int, sample_ids: Sequence[str] | None = None
    ) -> list[str]:
        return sample_test_sessions(
            team,
            sampling.condition_filter,
            count,
            quiet_period_seconds=session_quiet_period_seconds(sampling.settle),
            user=user,
            sample_ids=sample_ids,
        )

    def unit_id(self, unit: str) -> str:
        return unit

    def judge(self, evaluation: dict[str, Any], unit: str, user: User, reading: Reading) -> EvaluationActivityResult:
        return run_session_llm_judge(
            ExecuteSessionEvaluationInputs(
                evaluation=evaluation,
                team_id=evaluation["team_id"],
                session_id=unit,
                window_start=datetime.now(UTC).isoformat(),
            ),
            user=user,
            reading=reading,
        )


_UNITS: dict[contracts.EvaluationUnitKind, PreviewUnits[Any]] = {
    "generation": GenerationUnits(),
    "trace": TraceUnits(),
    "session": SessionUnits(),
}


def preview_units(target: contracts.EvaluationUnitKind) -> PreviewUnits[Any]:
    return _UNITS[target]


def preview_unit_count(target: contracts.EvaluationUnitKind, requested: int | None) -> int:
    """How many units a preview lists: the requested number, capped at what one test of this target covers."""
    return min(requested or DEFAULT_PREVIEW_UNITS, preview_units(target).max_units)


def sample_traffic(
    team: Team, user: User, scope: contracts.EvaluationPreviewScope, count: int | None
) -> list[contracts.EvaluationTrafficSample]:
    """The latest units an unsaved evaluation would run on, newest first. Raises `AIEventsUnavailableError`
    when `ai_events` has nothing to return."""
    units = preview_units(scope.target)
    unit_ids = units.sample_ids(team, user, preview_sampling(team, scope), preview_unit_count(scope.target, count))
    return [
        contracts.EvaluationTrafficSample(
            sample_id=preview.unit_id,
            sample_type=scope.target,
            trace_id=preview.trace_id,
            timestamp=preview.timestamp,
            input_preview=preview.io.input,
            output_preview=preview.io.output,
        )
        for preview in load_unit_previews(team, user, scope.target, unit_ids)
    ]
