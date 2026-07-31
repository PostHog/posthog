"""Force the HogQL type-aware simplifier on for a whole pytest session.

The snapshot suites already encode hundreds of real product queries and the ClickHouse SQL they
print to. Running them with the simplifier forced on turns that corpus into a change report: the
snapshot diff is every emitted-SQL shape that would change if ``typeAwareCastSimplification`` were
enabled in production.

    pytest posthog/hogql/printer --simplifier-canary
    git diff -- '*.ambr'

The diff is the artifact. Do not commit the churned snapshots — an updated snapshot silently
becomes the new expectation, which is the opposite of what this is for.
"""

from collections.abc import Iterator
from contextlib import contextmanager


@contextmanager
def type_aware_simplification_forced() -> Iterator[None]:
    """Opt every ``HogQLContext`` into the simplifier, however it was constructed.

    Wraps ``__post_init__`` rather than the printer gate so this reaches contexts that tests build
    directly as well as those built from team modifiers.

    Sets the internal context flag rather than the modifier. Both feed the same gate and the same
    transform, so the emitted SQL is identical either way, and the flag stays out of the serialized
    modifier payload that keys the query cache.
    """
    from posthog.hogql.context import HogQLContext  # noqa: PLC0415 — keeps HogQL off pytest's boot import path

    original_post_init = HogQLContext.__post_init__

    def post_init(self: HogQLContext) -> None:
        original_post_init(self)
        self.enable_type_aware_cast_simplification = True

    HogQLContext.__post_init__ = post_init  # type: ignore[method-assign] # ty: ignore[invalid-assignment]
    try:
        yield
    finally:
        HogQLContext.__post_init__ = original_post_init  # type: ignore[method-assign] # ty: ignore[invalid-assignment]
