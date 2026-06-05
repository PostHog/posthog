"""Suite-wide runner for the HogQL printer differential shadow-compare (``PRINTER_REARCHITECTURE.md`` §13).

This is the operable interface for the **equivalence gate**: it runs the real test suite with the compile-boundary hook
active (``HOGQL_SHADOW_DIFFERENTIAL=collect``), so every query the suite compiles is recompiled on the new lowering path
and compared to the served old-path SQL. It then reports, per dialect:

- how many compiles were **byte-identical** (the new path reproduces master exactly — the common, unmaterialized case);
- the **divergences** (new SQL differs — a materialized/optimized rewrite that is only *result*-equivalent, adjudicated
  by the execution net / the Celery shadow, or a genuine regression to fix toward master — §13.6);
- the **errors** (the new path failed to compile a query the old path handled — a fail-loud gap, §13.5).

It is the differential analogue of the (superseded) reachability-oracle runner: same suite-wide, single-process,
no-``-n`` mechanism, but it measures *equivalence* (does new == old?) instead of *reachability* (is old code reached?).

Run it as a plain script from the repo root (NOT ``python -m`` — that would import the ``posthog.hogql.printer`` package,
loading Django models, before this module can set Django up)::

    python posthog/hogql/printer/test/run_shadow_differential.py [pytest-paths...]

With no paths it sweeps a sensible default set. ``strict`` mode (fail the run on the first divergence) is available via
``--strict``; the default is ``collect`` (record everything, exit 0 on divergences so the full report is produced).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from posthog.hogql.printer.differential import ShadowRegistry


def _bootstrap_django() -> None:
    """Make the repo importable and the Django app registry ready before any ``posthog`` import (see oracle runner)."""
    repo_root = Path(__file__).resolve().parents[4]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
    # Must be set before the first ``posthog.models.person.util`` import: that module guards test-only symbols
    # (``bulk_create_persons``, ``create_person``) behind ``if TEST``, and conftest imports them. Importing the printers
    # (below, and during ``django.setup()``) pulls person.util in; without TEST the non-test module is cached and
    # conftest's import fails. Also makes ``settings.TEST`` true so the boundary hook's mode gate activates.
    os.environ.setdefault("TEST", "1")

    import django  # noqa: PLC0415 — bootstrap import, must follow the sys.path/env setup above
    from django.apps import apps  # noqa: PLC0415

    if not apps.ready:
        django.setup()


# The printer + transforms tests plus the end-to-end query path. ``test_query.py`` compiles a wide variety of real query
# shapes (joins, person/group properties, CTEs, subqueries) the corpus does not — the §8.3 coverage the sweep is for.
DEFAULT_PATHS: tuple[str, ...] = (
    "posthog/hogql/printer/test/",
    "posthog/hogql/transforms/test/",
    "posthog/hogql/test/test_query.py",
)

REPORT_PATH = Path(__file__).parent / "__golden__" / "shadow_differential_report.txt"


def run(paths: list[str], strict: bool) -> tuple[int, ShadowRegistry]:
    """Run pytest over ``paths`` with the boundary hook active; return ``(pytest_exit_code, registry)``."""
    # Deferred: importing differential loads the printers (→ Django models); must come after _bootstrap_django().
    import pytest  # noqa: PLC0415

    from posthog.hogql.printer.differential import SHADOW_ENV, get_registry, reset_registry  # noqa: PLC0415

    os.environ[SHADOW_ENV] = "strict" if strict else "collect"
    reset_registry()
    # Single process (no ``-n``) so the one registry accumulates every compile; ``-p no:randomly`` for stable ordering.
    exit_code = pytest.main(["-p", "no:randomly", "-q", *paths])
    return int(exit_code), get_registry()


def format_report(registry: ShadowRegistry) -> str:
    from posthog.hogql.printer.differential import ShadowDivergence  # noqa: PLC0415

    lines: list[str] = []
    lines.append("# HogQL printer differential shadow-compare — sweep report")
    lines.append("# Each compile the suite ran was recompiled on the new lowering path and compared to the old path.")
    lines.append(f"# total compiles observed: {registry.total}")
    lines.append(f"#   byte-identical (new == old): {registry.equivalent_count}")
    lines.append(
        f"#   divergences (new SQL differs — result-equivalent rewrite or regression): {len(registry.divergences)}"
    )
    lines.append(f"#   errors (new path failed to compile — fail-loud gap): {len(registry.errors)}")
    lines.append("")

    # Dedupe divergences by (dialect, old, new) so repeated test shapes collapse to one entry with a count.
    counts: dict[ShadowDivergence, int] = {}
    for divergence in registry.divergences:
        counts[divergence] = counts.get(divergence, 0) + 1
    if counts:
        lines.append(f"## divergences ({len(counts)} distinct)")
        for divergence, count in sorted(counts.items(), key=lambda kv: (kv[0].dialect, -kv[1])):
            lines.append(f"--- [{divergence.dialect}] x{count} ---")
            lines.append(f"  old: {divergence.old_sql}")
            lines.append(f"  new: {divergence.new_sql}")
        lines.append("")

    if registry.errors:
        lines.append(f"## errors ({len(registry.errors)})")
        seen: set[tuple[str, str]] = set()
        for error in registry.errors:
            key = (error.dialect, error.error)
            if key in seen:
                continue
            seen.add(key)
            lines.append(f"--- [{error.dialect}] {error.error} ---")
            lines.append(f"  old: {error.old_sql}")
        lines.append("")

    return "\n".join(lines) + "\n"


def summarize(registry: ShadowRegistry) -> str:
    return (
        f"shadow differential: {registry.total} compiles — "
        f"{registry.equivalent_count} identical, {len(registry.divergences)} diverged, {len(registry.errors)} errored"
    )


def main(argv: list[str]) -> int:
    _bootstrap_django()

    strict = "--strict" in argv
    paths = [arg for arg in argv if not arg.startswith("--")] or list(DEFAULT_PATHS)
    print(f"[shadow-differential] sweeping ({'strict' if strict else 'collect'}): {' '.join(paths)}", flush=True)  # noqa: T201

    exit_code, registry = run(paths, strict)

    REPORT_PATH.parent.mkdir(exist_ok=True)
    REPORT_PATH.write_text(format_report(registry))

    print("\n" + summarize(registry), flush=True)  # noqa: T201
    print(f"[shadow-differential] wrote report to {REPORT_PATH}", flush=True)  # noqa: T201
    print(f"[shadow-differential] pytest exit code: {exit_code}", flush=True)  # noqa: T201
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
