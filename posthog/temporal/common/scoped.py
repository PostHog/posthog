import inspect
import functools
from collections.abc import Callable, Coroutine
from typing import Any, ParamSpec, TypeVar

import posthoganalytics

from posthog.temporal.common.posthog_client import is_expected_activity_failure

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
            # Capture here instead of in new_context so expected failures (egress budget sheds,
            # cancellations) skip error tracking, as they do in the worker interceptor.
            with posthoganalytics.new_context(fresh=fresh, capture_exceptions=False):
                try:
                    return await func(*args, **kwargs)
                except Exception as error:
                    if capture_exceptions and not is_expected_activity_failure(error):
                        posthoganalytics.capture_exception(error)
                    raise

        return wrapper

    return decorator
