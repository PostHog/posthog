import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from posthog.dataclasses import frozen

from .errors import RecipeTimeoutError


@frozen
class _Deadline:
    seconds: float
    expires_at: float


# The deadline lives in the context rather than in an argument, so every expression evaluation and predicate test can
# check the clock without each signature carrying it.
_active_deadline: ContextVar[_Deadline | None] = ContextVar("recipe_deadline", default=None)


@contextmanager
def time_limit(seconds: float) -> Iterator[None]:
    token = _active_deadline.set(_Deadline(seconds=seconds, expires_at=time.monotonic() + seconds))
    try:
        yield
    finally:
        _active_deadline.reset(token)


def check_time_limit() -> None:
    deadline = _active_deadline.get()
    if deadline is not None and time.monotonic() >= deadline.expires_at:
        raise RecipeTimeoutError(
            f"RecipeNormalizer: exceeded the time limit ({deadline.seconds}s) because a recipe does too much work for this event"
        )
