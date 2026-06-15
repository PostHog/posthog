"""shrinkray-backed test-case minimiser for the parser-parity diagnostics.

The diagnostics in this directory find queries where two parser backends
disagree, then reduce each one to a minimal repro a human can paste into a
regression test. The reduction used to be a hand-rolled greedy
delete-one-token pass; this module replaces it with
[shrinkray](https://github.com/DRMacIver/shrinkray), a multi-format
test-case reducer by the author of Hypothesis. shrinkray shrinks *within*
tokens too (smaller identifiers, smaller numbers, collapsed structure), so
it lands on tighter repros than token deletion alone.

shrinkray is an **optional** dependency — it lives in the
`hogql-parser-parity` dependency group, not the default dev install, so its
heavy transitive deps (textual, libcst, black) aren't forced on every dev.
Callers gate on `is_available()` and only reach `shrink()` once it's
confirmed present; the imports here are deferred so importing this module
(and the diagnostics) never hard-requires shrinkray.

`shrink()` is generic over a `str -> bool` interestingness predicate, so it
knows nothing about divergence shapes — the diagnostic-aware wrapper
(`shrink_to_shape` in `_diagnostic_common`) builds the predicate.
"""

from __future__ import annotations

from collections.abc import Callable
from random import Random


class ShrinkrayUnavailable(RuntimeError):
    """shrinkray (an optional dependency) isn't importable.

    Raised by `shrink()` when the `hogql-parser-parity` group hasn't been
    installed. Callers should probe `is_available()` up front and surface a
    clear install hint rather than letting this fire mid-grind.
    """


def is_available() -> bool:
    """Whether shrinkray (and its trio runtime) can be imported."""
    try:
        import trio  # noqa: F401, PLC0415 — optional dep probe
        import shrinkray  # noqa: F401, PLC0415 — optional dep probe
    except ImportError:
        return False
    return True


def shrink(initial: str, is_interesting: Callable[[str], bool], *, parallelism: int = 1) -> str:
    """Reduce `initial` to the smallest string that still satisfies
    `is_interesting`, using shrinkray.

    `is_interesting` is a plain synchronous predicate over the candidate
    text. It's wrapped in the async, bytes-typed predicate shrinkray wants:
    candidates that aren't valid UTF-8 or are blank are treated as not
    interesting (shrinkray works on raw bytes and will probe both). The
    returned string is guaranteed to satisfy `is_interesting` — shrinkray
    only ever moves to smaller *interesting* test cases, and never below the
    initial one.

    If `is_interesting(initial)` is false, there's nothing to reduce toward,
    so `initial` is returned unchanged. Any other shrinkray error
    propagates — the grind-robustness fallback (return the original query on
    failure) lives in the caller, so this stays a thin, reusable utility.

    Raises `ShrinkrayUnavailable` if shrinkray isn't installed.
    """
    try:
        import trio  # noqa: PLC0415 — optional dep, kept off the import path
        from shrinkray.problem import BasicReductionProblem, InvalidInitialExample  # noqa: PLC0415
        from shrinkray.reducer import ShrinkRay  # noqa: PLC0415
        from shrinkray.work import Volume, WorkContext  # noqa: PLC0415
    except ImportError as e:
        raise ShrinkrayUnavailable(
            "shrinkray is not installed — install the optional parity group with "
            "`uv sync --group hogql-parser-parity`, or re-run without --shrink-failures"
        ) from e

    async def predicate(test_case: bytes) -> bool:
        try:
            text = test_case.decode("utf-8")
        except UnicodeDecodeError:
            return False
        if not text.strip():
            return False
        return is_interesting(text)

    async def drive() -> bytes:
        # Random(0) + parallelism=1 → deterministic reductions, so two runs
        # over the same divergence land on the same minimal repro (the
        # predicate is CPU-bound and synchronous; concurrency wouldn't help).
        work = WorkContext(random=Random(0), parallelism=parallelism, volume=Volume.quiet)
        problem = BasicReductionProblem(initial=initial.encode("utf-8"), is_interesting=predicate, work=work)
        try:
            await problem.setup()  # validates the initial example is interesting
        except InvalidInitialExample:
            return initial.encode("utf-8")
        await ShrinkRay(target=problem).run()
        return problem.current_test_case

    return trio.run(drive).decode("utf-8")
