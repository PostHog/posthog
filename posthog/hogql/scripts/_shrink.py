"""shrinkray-backed test-case minimiser for the parser-parity diagnostics.

The diagnostics in this directory find queries where two parser backends
disagree, then reduce each one to a minimal repro a human can paste into a
regression test. The reduction used to be a hand-rolled greedy
delete-one-token pass; this module replaces it with
[shrinkray](https://github.com/DRMacIver/shrinkray), a multi-format
test-case reducer by the author of Hypothesis. shrinkray shrinks *within*
tokens too (smaller identifiers, smaller numbers, collapsed structure), so
it lands on tighter repros than token deletion alone.

shrinkray lives in the optional `hogql-parser-parity` dependency group, not
the default dev install, so its heavy transitive deps (textual, libcst,
black) aren't forced on every dev. The parity diagnostics that import this
module therefore require that group — `uv sync --group hogql-parser-parity`
— and fail at import with a plain `ModuleNotFoundError` without it. That's
the deliberate trade: these are parity-work-only scripts, so they may simply
require the parity dependency rather than carry a graceful-degradation path.

`shrink()` is generic over a `str -> bool` interestingness predicate, so it
knows nothing about divergence shapes — the diagnostic-aware wrapper
(`shrink_to_shape` in `_diagnostic_common`) builds the predicate.
"""

from __future__ import annotations

from collections.abc import Callable
from random import Random

import trio
from shrinkray.problem import BasicReductionProblem, InvalidInitialExample
from shrinkray.reducer import ShrinkRay
from shrinkray.work import Volume, WorkContext


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
    """

    async def predicate(test_case: bytes) -> bool:
        # shrinkray cancels between predicate calls at its own checkpoint, so a
        # blocking body is fine here.
        await trio.lowlevel.checkpoint()
        try:
            text = test_case.decode("utf-8")
        except UnicodeDecodeError:
            return False
        if not text.strip():
            return False
        # is_interesting is GIL-bound CPU work (parses with both backends): a
        # worker thread buys no parallelism, and parallelism is pinned to 1, so
        # call it directly rather than paying a `to_thread` hop per candidate.
        return is_interesting(text)

    async def drive() -> bytes:
        # Random(0) + parallelism=1 → deterministic repros; the predicate is CPU-bound and synchronous, so concurrency wouldn't help anyway.
        work = WorkContext(random=Random(0), parallelism=parallelism, volume=Volume.quiet)
        problem = BasicReductionProblem(initial=initial.encode("utf-8"), is_interesting=predicate, work=work)
        try:
            await problem.setup()  # validates the initial example is interesting
        except InvalidInitialExample:
            return initial.encode("utf-8")
        await ShrinkRay(target=problem).run()
        return problem.current_test_case

    return trio.run(drive).decode("utf-8")
