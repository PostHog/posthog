import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Final

from posthog.dataclasses import frozen

from .errors import RecipeOutputLimitError, RecipeRuntimeError, RecipeTimeoutError

# Every ceiling sits far above what any renderable trace produces. They exist so a pathological team recipe fails
# fast instead of pinning a server worker.
MAX_OPERATIONS: Final = 250_000
MAX_MESSAGES: Final = 25_000
# Recipe values hold references, so a recipe can cheaply build a value whose serialized form is exponentially larger
# than the work it took to build, or copy a large list once per item of another. These bound every value a run builds,
# copies, parses or serializes, to bound the memory one run can take. Each site charges before it allocates: one value
# per list item, mapping entry or serialized value, and one character per character of text it builds. A JSON parse
# charges after it succeeds instead, and only when its result is kept, because no cheap scan of the text can say how many
# values it holds.
MAX_OUTPUT_NODES: Final = 1_000_000
# Events can carry inline base64 media of tens of megabytes, and every pass that produces text charges it again, for
# example interpolating it into a data URI and then serializing the message. The character cap leaves room for that.
MAX_OUTPUT_CHARS: Final = 64_000_000
# A parse runs to completion before anything can charge it or check the clock, and it can allocate tens of bytes per
# character, such as a 56-byte list for each `[],`. Longer text stays raw text, which bounds the memory and the time of
# one parse.
MAX_PARSE_CHARS: Final = 6_000_000
# Copying or serializing a value evaluates no expression, so the output budget checks the clock itself.
OUTPUT_NODES_PER_CLOCK_CHECK: Final = 1_000


@frozen
class _Deadline:
    seconds: float
    expires_at: float


class ExecutionBudget:
    def __init__(self) -> None:
        self._operations = 0
        self._messages = 0
        self._output_nodes = 0
        self._output_chars = 0
        self._next_clock_check = OUTPUT_NODES_PER_CLOCK_CHECK

    def charge_operations(self, count: int) -> None:
        self._operations += count
        if self._operations > MAX_OPERATIONS:
            raise RecipeRuntimeError(
                f"RecipeNormalizer: exceeded the operation budget ({MAX_OPERATIONS}) — a recipe expands this event into too much work"
            )

    def charge_messages(self, count: int) -> None:
        self._messages += count
        if self._messages > MAX_MESSAGES:
            raise RecipeRuntimeError(
                f"RecipeNormalizer: exceeded the message budget ({MAX_MESSAGES}) — a recipe expands this event into too many messages"
            )

    def charge_output(self, *, nodes: int = 0, chars: int = 0) -> None:
        self._output_nodes += nodes
        self._output_chars += chars
        if self._output_nodes > MAX_OUTPUT_NODES:
            raise RecipeOutputLimitError(
                f"RecipeNormalizer: exceeded the output budget ({MAX_OUTPUT_NODES} values) because a recipe builds too much output for this event"
            )
        if self._output_chars > MAX_OUTPUT_CHARS:
            raise RecipeOutputLimitError(
                f"RecipeNormalizer: exceeded the output budget ({MAX_OUTPUT_CHARS} characters) because a recipe builds too much output for this event"
            )
        if self._output_nodes >= self._next_clock_check:
            self._next_clock_check = self._output_nodes + OUTPUT_NODES_PER_CLOCK_CHECK
            check_time_limit()


# The deadline and the budget live in the context rather than in arguments, so every expression evaluation, predicate
# test and serialization can reach them without each signature carrying them.
_active_deadline: ContextVar[_Deadline | None] = ContextVar("recipe_deadline", default=None)
_active_budget: ContextVar[ExecutionBudget | None] = ContextVar("recipe_budget", default=None)


@contextmanager
def time_limit(seconds: float) -> Iterator[None]:
    requested = _Deadline(seconds=seconds, expires_at=time.monotonic() + seconds)
    outer = _active_deadline.get()
    # A nested limit only tightens the deadline, so a caller can bound every run it makes as a whole.
    deadline = outer if outer is not None and outer.expires_at <= requested.expires_at else requested
    token = _active_deadline.set(deadline)
    try:
        yield
    finally:
        _active_deadline.reset(token)


@contextmanager
def execution_budget() -> Iterator[None]:
    # A nested budget joins the outer one, so a caller can bound every run it makes as a whole.
    if _active_budget.get() is not None:
        yield
        return
    token = _active_budget.set(ExecutionBudget())
    try:
        yield
    finally:
        _active_budget.reset(token)


@contextmanager
def run_limits(seconds: float) -> Iterator[None]:
    with execution_budget(), time_limit(seconds):
        yield


def check_time_limit() -> None:
    deadline = _active_deadline.get()
    if deadline is not None and time.monotonic() >= deadline.expires_at:
        raise RecipeTimeoutError(
            f"RecipeNormalizer: exceeded the time limit ({deadline.seconds}s) because a recipe does too much work for this event"
        )


def charge_operations(count: int) -> None:
    budget = _active_budget.get()
    if budget is not None:
        budget.charge_operations(count)


def charge_messages(count: int) -> None:
    budget = _active_budget.get()
    if budget is not None:
        budget.charge_messages(count)


def charge_output(*, nodes: int = 0, chars: int = 0) -> None:
    budget = _active_budget.get()
    if budget is not None:
        budget.charge_output(nodes=nodes, chars=chars)
