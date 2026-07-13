from __future__ import annotations

import inspect
import logging
import importlib
from collections.abc import Callable, Coroutine, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .context import EvalContext

logger = logging.getLogger(__name__)

SANDBOXED_PACKAGE = "ee.hogai.eval.sandboxed"
SANDBOXED_ROOT = Path(__file__).resolve().parent.parent

EvalSuiteFn = Callable[["EvalContext"], Coroutine[Any, Any, None]]


class SuiteDiscoveryError(RuntimeError):
    pass


@dataclass(frozen=True)
class EvalSuite:
    domain: str
    """Directory the suite lives in, e.g. ``experiments``. ``root`` for top-level files."""

    module_name: str
    fn_name: str
    fn: EvalSuiteFn

    @property
    def id(self) -> str:
        return f"{self.domain}/{self.module_name}::{self.fn_name}"


def _module_path(path: Path) -> tuple[str, str, str]:
    relative = path.relative_to(SANDBOXED_ROOT)
    domain = relative.parent.as_posix().replace("/", ".") if relative.parent != Path(".") else "root"
    dotted_parent = "" if domain == "root" else f".{domain}"
    return domain, path.stem, f"{SANDBOXED_PACKAGE}{dotted_parent}.{path.stem}"


def discover_suites(selectors: Sequence[str] = ()) -> list[EvalSuite]:
    """Import every ``eval_*.py`` under the sandboxed tree and collect its ``eval_*`` coroutines.

    Convention over registry: a new eval file is picked up with no boilerplate,
    and its domain falls out of the directory it lives in.
    """
    suites: list[EvalSuite] = []
    for path in sorted(SANDBOXED_ROOT.rglob("eval_*.py")):
        if path.is_relative_to(Path(__file__).resolve().parent):
            continue
        domain, module_name, dotted = _module_path(path)
        try:
            module = importlib.import_module(dotted)
        except Exception as e:
            # A selected run only cares about the modules its selectors target.
            # A broken *unrelated* module shouldn't take the whole run down — but a
            # no-selector run (full run or --list) is the repo's import smoke check,
            # so there it stays fatal.
            #
            # We match selectors against ``<domain>/<module>`` (not the full
            # ``<domain>/<module>::<fn>`` suite id): a module that failed to import
            # has no function names to build ids from. A ``::fn``-style selector
            # therefore can't match here and the module is treated as unrelated —
            # acceptable, since such a selector still fails the run loudly via the
            # "No eval suites matched" check below.
            module_target = f"{domain}/{module_name}"
            if selectors and not any(selector in module_target for selector in selectors):
                logger.warning("Skipping unselected eval module %s that failed to import: %s", dotted, e)
                continue
            raise SuiteDiscoveryError(f"Failed to import eval module {dotted}: {e}") from e
        for fn_name, fn in vars(module).items():
            if not fn_name.startswith("eval_") or not inspect.iscoroutinefunction(fn):
                continue
            # Only functions defined here — an `eval_*` imported from a sibling
            # module would otherwise be collected twice.
            if fn.__module__ != dotted:
                continue
            suites.append(EvalSuite(domain=domain, module_name=module_name, fn_name=fn_name, fn=fn))

    if not selectors:
        return suites

    selected = [suite for suite in suites if any(selector in suite.id for selector in selectors)]
    if not selected:
        raise SuiteDiscoveryError(
            f"No eval suites matched {list(selectors)}. Run with --list to see the available suite ids."
        )
    return selected
