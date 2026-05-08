import inspect
import functools
from collections.abc import Callable, Coroutine
from typing import Any, ParamSpec, TypeVar

import posthoganalytics

P = ParamSpec("P")
R = TypeVar("R")

_AsyncFn = Callable[P, Coroutine[Any, Any, R]]


# Async-aware variant of posthoganalytics.scoped(), safe to stack on async Temporal activities.
# The regular version returns an unawaited coroutine and crashes on JSON encoding.
def scoped_temporal(fresh: bool = False, capture_exceptions: bool = True) -> Callable[[_AsyncFn[P, R]], _AsyncFn[P, R]]:
    def decorator(func: _AsyncFn[P, R]) -> _AsyncFn[P, R]:
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
