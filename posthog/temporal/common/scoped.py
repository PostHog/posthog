import inspect
import functools
from collections.abc import Awaitable, Callable
from typing import ParamSpec, TypeVar

import posthoganalytics

P = ParamSpec("P")
R = TypeVar("R")


# Async-aware variant of posthoganalytics.scoped(), safe to stack on async Temporal activities.
# The regular version returns an unawaited coroutine and crashes on JSON encoding.
def scoped_temporal(
    fresh: bool = False, capture_exceptions: bool = True
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    def decorator(func: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        if not inspect.iscoroutinefunction(func):
            raise TypeError(
                f"@scoped_temporal() requires an async function; got {func!r}. "
                f"Use @posthoganalytics.scoped() for sync functions."
            )

        @functools.wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            with posthoganalytics.new_context(fresh=fresh, capture_exceptions=capture_exceptions):
                return await func(*args, **kwargs)

        return wrapper

    return decorator
