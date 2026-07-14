"""The Braintrust engine — the default (and currently only) ``EvalEngine``."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from braintrust import EvalAsync, EvalCase
from braintrust.framework import EvalResultWithSummary

from ..harness.reporting import QUIET_REPORTER
from .base import EvalTaskFn


class BraintrustEngine:
    """Runs experiments on Braintrust and reports through it.

    These knobs are load-bearing invariants (they used to live in
    ``harness/AGENTS.md``); breaking one produces a hang or a silently wrong
    result rather than an exception:

    - **Never pass a ``timeout``.** ``EvalAsync``'s timeout wraps the whole task
      invocation, including time a case spends queued on the harness's own
      concurrency semaphores, so it would kill cases that never started. The
      per-case budget belongs in the ``asyncio.wait_for`` inside the run's
      ``_execute_case``, which starts only after slot acquisition.
    - **Never let ``max_concurrency`` bind.** It is set to the total case count
      (cases × trials) so the harness's semaphores are the only limiters.
    - **``QUIET_REPORTER``.** Suites share one stdout; the quiet reporter stops
      each experiment from dumping its own score table into the interleaved
      stream. Its callbacks are called synchronously by ``EvalAsync`` and must
      not be coroutines.
    - **``update=True``.** Experiment names stay runtime/model-agnostic so history
      lines up across runs; updating keeps that history rather than forking it.
    """

    async def run_experiment(
        self,
        *,
        project_name: str,
        cases: Sequence[EvalCase],
        task: EvalTaskFn,
        scorers: Sequence[Any],
        trial_count: int,
        is_public: bool,
        no_send_logs: bool,
        metadata: dict[str, Any],
    ) -> EvalResultWithSummary:
        return await EvalAsync(
            project_name,
            data=list(cases),
            task=task,
            scores=list(scorers),
            trial_count=trial_count,
            # Our global concurrency semaphores are the only limiters that should
            # bind. Braintrust's own per-suite limiter must never gate, so let it
            # admit every case at once — across all trials.
            max_concurrency=max(len(cases) * trial_count, 1),
            # Braintrust's timeout wraps the whole task invocation, including any
            # time a case spends queued on our concurrency semaphores — so a queued
            # case would be killed before it ever started. The real budget is the
            # ``asyncio.wait_for`` inside ``_execute_case``.
            timeout=None,
            # Suites share one stdout; the quiet reporter stops each experiment
            # from dumping its own score table into the interleaved stream.
            reporter=QUIET_REPORTER,
            update=True,
            is_public=is_public,
            no_send_logs=no_send_logs,
            # Experiment names stay runtime/model-agnostic so history lines up
            # across runs; the metadata is what lets Braintrust filter or compare.
            metadata=metadata,
        )
