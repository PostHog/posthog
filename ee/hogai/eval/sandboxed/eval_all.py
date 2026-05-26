"""Batch runner that gathers every sandboxed ``eval_*`` into one event loop.

Why this exists: pytest runs each ``eval_*`` function serially, so a test with a
single eval case leaves all of ``--sandbox-concurrency``'s Docker slots idle
until it finishes. The batch runner imports every ``eval_*`` coroutine, packs
them into one ``asyncio.gather`` under a session-wide semaphore (see
``SandboxedDemoData.get_concurrency_semaphore``), and lets cases from
heterogeneous eval suites share one Docker-slot budget — the long-tail
single-case suite no longer blocks the rest.

Each ``eval_*`` still calls its own ``SandboxedEval(...)``, so the Braintrust
experiment-per-suite layout is preserved. The wall-clock win comes from
interleaving cases across suites, not from collapsing them into one experiment.

To run::

    pytest ee/hogai/eval/sandboxed/eval_all.py --concurrent-evals

When ``--concurrent-evals`` is passed, the individual ``eval_*`` tests under
``ee/hogai/eval/sandboxed/`` are deselected (see ``conftest.py``) so the suite
isn't double-run.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import logging
import pkgutil
from collections.abc import Callable
from typing import Any

import pytest

logger = logging.getLogger(__name__)


_THIS_MODULE_NAME = __name__


def _discover_eval_functions() -> list[tuple[str, Callable[..., Any]]]:
    """Walk ``ee.hogai.eval.sandboxed`` and return every ``async def eval_*``.

    Returns a list of ``(fully_qualified_name, function)`` pairs sorted for
    deterministic ordering. Skips the batch module itself to avoid infinite
    recursion.
    """
    import ee.hogai.eval.sandboxed as root_pkg

    fns: list[tuple[str, Callable[..., Any]]] = []
    seen: set[Callable[..., Any]] = set()
    for _finder, modname, _ispkg in pkgutil.walk_packages(
        root_pkg.__path__, prefix=root_pkg.__name__ + "."
    ):
        leaf = modname.rsplit(".", 1)[-1]
        if not leaf.startswith("eval_"):
            continue
        if modname == _THIS_MODULE_NAME:
            continue
        try:
            mod = importlib.import_module(modname)
        except Exception:
            logger.exception("Failed to import %s while discovering eval functions", modname)
            continue
        for attr_name in dir(mod):
            if not attr_name.startswith("eval_"):
                continue
            attr = getattr(mod, attr_name)
            if not asyncio.iscoroutinefunction(attr):
                continue
            if attr in seen:
                continue
            seen.add(attr)
            fns.append((f"{modname}.{attr_name}", attr))
    fns.sort(key=lambda pair: pair[0])
    return fns


def _bind_fixtures(
    fn: Callable[..., Any],
    *,
    sandboxed_demo_data: Any,
    pytestconfig: pytest.Config,
    posthog_client: Any,
    mcp_mode: str,
) -> dict[str, Any]:
    """Resolve the subset of standard eval fixtures this function declares."""
    sig = inspect.signature(fn)
    available = {
        "sandboxed_demo_data": sandboxed_demo_data,
        "pytestconfig": pytestconfig,
        "posthog_client": posthog_client,
        "mcp_mode": mcp_mode,
    }
    return {name: value for name, value in available.items() if name in sig.parameters}


async def eval_all_sandboxed(sandboxed_demo_data, pytestconfig, posthog_client, mcp_mode):
    """Run every discovered ``eval_*`` concurrently under one event loop.

    Each suite contributes its own ``SandboxedEval`` call (own Braintrust
    experiment). Docker concurrency is gated by the session-wide semaphore on
    ``SandboxedDemoData`` (see ``get_concurrency_semaphore``) — sized via
    ``--sandbox-concurrency``.

    Parametrized by ``mcp_mode`` (autouse fixture chain): when running with
    ``--mcp-mode both``, this function fires twice — once per mode. Each
    invocation gathers every suite, which is what we want: the
    ``SANDBOX_MCP_URL`` override applied by the ``_apply_mcp_mode`` autouse
    fixture is uniform across that gathered batch.
    """
    fns = _discover_eval_functions()
    if not fns:
        pytest.skip("No sandboxed eval_* functions discovered")

    logger.info(
        "Batch runner dispatching %d eval_* suites concurrently (mcp_mode=%s)", len(fns), mcp_mode
    )

    async def _run_one(name: str, fn: Callable[..., Any]) -> None:
        kwargs = _bind_fixtures(
            fn,
            sandboxed_demo_data=sandboxed_demo_data,
            pytestconfig=pytestconfig,
            posthog_client=posthog_client,
            mcp_mode=mcp_mode,
        )
        try:
            await fn(**kwargs)
        except Exception:
            logger.exception("Suite %s failed in batch runner", name)
            raise

    results = await asyncio.gather(
        *(_run_one(name, fn) for name, fn in fns), return_exceptions=True
    )

    failures = [
        (name, result)
        for (name, _fn), result in zip(fns, results, strict=True)
        if isinstance(result, BaseException)
    ]
    if failures:
        summary = ", ".join(f"{name}: {type(err).__name__}" for name, err in failures)
        # Re-raise the first failure so pytest reports a real traceback; surface
        # the rest in the message.
        first_name, first_err = failures[0]
        raise AssertionError(
            f"{len(failures)} of {len(fns)} sandboxed eval suites failed in batch runner "
            f"(first: {first_name}): {summary}"
        ) from first_err
