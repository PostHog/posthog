"""A user-written Hog program that decides one window, bounded so it cannot delay another alert.

The program runs after the query and before the lifecycle, inside the same sync evaluate
activity, and returns one boolean per window. The lifecycle keeps N-of-M, cooldown, mute and
resolve, so a custom condition changes what "breached" means and nothing else.

Two limits protect the batch. A CPU budget shared by every condition in the batch stops the
whole stage once it is spent, and a wall timeout per run stops a runaway loop. The CPU budget is
the primary limit because wall time on a worker with fifty activity threads is contended for the
GIL: measured, a correct 0.15 ms program can wait over 200 ms for its turn, so a short wall
timeout fails correct programs. A wall timeout with little CPU behind it is therefore the
worker's contention, not the user's loop, and is reported as transient.
"""

import time
from collections.abc import Sequence
from datetime import timedelta
from typing import Any

from posthog.hogql.compiler.bytecode import create_bytecode
from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_program

from posthog.dataclasses import frozen

from common.hogvm.python.execute import execute_bytecode
from common.hogvm.python.stl import BLOCKING_FUNCTIONS
from common.hogvm.python.utils import HogVMMemoryExceededException, HogVMRuntimeExceededException

# A guard against a runaway loop, deliberately generous: the CPU budget below is the real limit.
CONDITION_RUN_TIMEOUT = timedelta(seconds=1)
# The Rust VM defaults to 1 MiB; 64 MiB (the Python default) times fifty activity threads is 3 GiB.
CONDITION_MEMORY_LIMIT = 4 * 1024 * 1024
# CPU time every condition in one batch shares. It sits under the gap between the batch query
# budget and the evaluate activity's start-to-close, so 200 alerts cannot spend the activity.
CONDITION_BATCH_BUDGET = timedelta(seconds=2)
CONDITION_MAX_SOURCE_BYTES = 8 * 1024
# Wall time the batch's conditions may take together. The CPU budget above does not see time a
# run spends waiting for the GIL, and many such waits could still spend the activity's timeout.
CONDITION_BATCH_WALL_BUDGET = timedelta(seconds=5)
# Below this share of the wall timeout spent on CPU, a timeout is contention, not the program.
CONDITION_OWN_TIME_SHARE = 0.5

# As many windows as a configuration can evaluate, so a program that reads a deep window is not
# refused for a null the synthetic input never had.
_DRY_RUN_VALUES = tuple(float(24 - index) for index in range(24))


class AlertConditionValidationError(Exception):
    def __init__(self, message: str, *, field: str | None = "condition_source") -> None:
        super().__init__(message)
        self.message = message
        self.field = field


@frozen
class ConditionContext:
    """What one window looks like to the program. Kept small: the VM copies globals on access."""

    value: float | None
    values: tuple[float | None, ...]
    previous: float | None
    window: dict[str, float | None]
    labels: dict[str, str]
    threshold: dict[str, Any]
    timestamp: str

    def as_globals(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "values": list(self.values),
            "previous": self.previous,
            "window": dict(self.window),
            "labels": dict(self.labels),
            "threshold": dict(self.threshold),
            "timestamp": self.timestamp,
        }


@frozen
class ConditionResult:
    breached: bool | None
    error: str | None = None
    transient: bool = False
    duration_ms: float = 0.0


class ConditionBudget:
    """CPU time the conditions of one batch may spend together."""

    def __init__(
        self,
        total: timedelta = CONDITION_BATCH_BUDGET,
        run_timeout: timedelta = CONDITION_RUN_TIMEOUT,
        wall_total: timedelta = CONDITION_BATCH_WALL_BUDGET,
    ) -> None:
        self._total = total.total_seconds()
        self._wall_total = wall_total.total_seconds()
        self._run_timeout = run_timeout
        self._spent = 0.0
        self._started_at: float | None = None

    def take(self) -> timedelta | None:
        """The wall timeout for the next run, or None once the batch's CPU or wall budget is spent."""
        if self._started_at is None:
            self._started_at = time.perf_counter()
        if self._spent >= self._total or time.perf_counter() - self._started_at > self._wall_total:
            return None
        return self._run_timeout

    def spend(self, cpu_seconds: float) -> None:
        self._spent += max(cpu_seconds, 0.0)


def _stats(values: Sequence[float | None]) -> dict[str, float | None]:
    present = [v for v in values if v is not None]
    if not present:
        return {"min": None, "max": None, "avg": None, "sum": None, "count": 0.0}
    return {
        "min": min(present),
        "max": max(present),
        "avg": sum(present) / len(present),
        "sum": sum(present),
        "count": float(len(present)),
    }


def build_condition_contexts(
    values_newest_first: Sequence[float | None],
    *,
    evaluation_periods: int,
    labels: dict[str, str],
    threshold: dict[str, Any],
    window_ends: Sequence[str],
) -> tuple[ConditionContext, ...]:
    """One context per evaluated window, newest first, so the lifecycle's N-of-M reads the
    program's answers the way it reads the threshold's."""
    contexts = []
    for index in range(evaluation_periods):
        values = tuple(values_newest_first[index:])
        contexts.append(
            ConditionContext(
                value=values[0] if values else None,
                values=values,
                previous=values[1] if len(values) > 1 else None,
                window=_stats(values),
                labels=dict(labels),
                threshold=dict(threshold),
                timestamp=window_ends[index] if index < len(window_ends) else "",
            )
        )
    return tuple(contexts)


def compile_condition_bytecode(source: str) -> list[Any]:
    """Bytecode for the program as written. `compile_alert_condition` is what a writer calls; this
    is the compile step alone, for a caller that runs its own check."""
    if not source or not source.strip():
        raise AlertConditionValidationError("Condition is empty")
    if len(source.encode()) > CONDITION_MAX_SOURCE_BYTES:
        raise AlertConditionValidationError(f"Condition is too long (max {CONDITION_MAX_SOURCE_BYTES // 1024} KiB)")
    try:
        program = parse_program(source)
        # No async functions: a condition cannot fetch, capture or run anything.
        return create_bytecode(program, supported_functions=set(), context=HogQLContext(team_id=None)).bytecode
    except Exception as error:
        raise AlertConditionValidationError(f"Condition has errors: {str(error).splitlines()[0][:200]}") from error


def compile_alert_condition(source: str) -> list[Any]:
    """Bytecode for a program the check can run, or a validation error a writer can show. A dry
    run against a synthetic window rejects a program that cannot finish or does not answer."""
    bytecode = compile_condition_bytecode(source)
    dry_run = run_alert_condition(
        bytecode,
        build_condition_contexts(
            _DRY_RUN_VALUES,
            evaluation_periods=1,
            labels={},
            threshold={"count": 10, "operator": "above"},
            window_ends=("2000-01-01T00:00:00+00:00",),
        )[0],
        ConditionBudget(),
    )
    if dry_run.error is not None:
        raise AlertConditionValidationError(f"Condition has errors: {dry_run.error}")
    return bytecode


def run_alert_condition(bytecode: list[Any], context: ConditionContext, budget: ConditionBudget) -> ConditionResult:
    """Runs one window through the program. Never raises: every failure is a result the caller
    records against this alert alone."""
    timeout = budget.take()
    if timeout is None:
        return ConditionResult(breached=None, error="condition budget for this batch is spent", transient=True)

    wall_start, cpu_start = time.perf_counter(), time.thread_time()
    error: str | None = None
    transient = False
    result: Any = None
    try:
        result = execute_bytecode(
            bytecode,
            globals=context.as_globals(),
            timeout=timeout,
            memory_limit=CONDITION_MEMORY_LIMIT,
            disallowed_functions=BLOCKING_FUNCTIONS,
        ).result
    except HogVMRuntimeExceededException:
        cpu = time.thread_time() - cpu_start
        transient = cpu < timeout.total_seconds() * CONDITION_OWN_TIME_SHARE
        error = f"condition timed out after {int(timeout.total_seconds() * 1000)} ms"
        if transient:
            error += " while the worker was busy"
    except HogVMMemoryExceededException:
        error = f"condition used more than {CONDITION_MEMORY_LIMIT // (1024 * 1024)} MiB of memory"
    except Exception as failure:
        # The type only: a message could carry the values the program was given.
        error = f"condition failed: {type(failure).__name__}"
    cpu_elapsed = time.thread_time() - cpu_start
    budget.spend(cpu_elapsed)
    duration_ms = (time.perf_counter() - wall_start) * 1000

    if error is not None:
        return ConditionResult(breached=None, error=error, transient=transient, duration_ms=duration_ms)
    if not isinstance(result, bool):
        return ConditionResult(breached=None, error="condition must return true or false", duration_ms=duration_ms)
    return ConditionResult(breached=result, duration_ms=duration_ms)


@frozen
class ConditionVerdict:
    """The program's answer for every evaluated window, newest first, or why there is none."""

    flags: tuple[bool, ...] | None
    error: str | None = None
    transient: bool = False
    duration_ms: float = 0.0

    @property
    def failure_reason(self) -> str:
        return "budget" if self.transient and self.error and "budget" in self.error else "program"


def evaluate_condition_windows(
    bytecode: list[Any], contexts: Sequence[ConditionContext], budget: ConditionBudget
) -> ConditionVerdict:
    """Runs every window through the program. The first window that fails ends the verdict, so a
    program that cannot answer one window answers none."""
    flags: list[bool] = []
    duration_ms = 0.0
    for context in contexts:
        result = run_alert_condition(bytecode, context, budget)
        duration_ms += result.duration_ms
        if result.error is not None or result.breached is None:
            return ConditionVerdict(
                flags=None,
                error=result.error or "condition must return true or false",
                transient=result.transient,
                duration_ms=duration_ms,
            )
        flags.append(result.breached)
    return ConditionVerdict(flags=tuple(flags), duration_ms=duration_ms)
