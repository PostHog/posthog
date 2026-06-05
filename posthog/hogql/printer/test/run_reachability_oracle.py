"""Suite-wide runner for the HogQL printer reachability oracle (PR0b).

This is the self-contained tool that captures the **master baseline** — the set of properties that still reach the
printer's property-decision code — and, later in the migration, proves that set shrank to empty per dialect (the gate
for deleting the printer's property machinery; see ``posthog/hogql/PRINTER_REARCHITECTURE.md`` §9.3, §12.5, §8.3).

It activates the oracle instrumentation for the whole process, runs ``pytest.main`` over the given test paths (in the
same process — do NOT pass ``-n``, parallel workers would each instrument their own process and the aggregation would
be lost), aggregates every reach across the entire run, writes a sorted human-readable report, and prints a summary.

Why suite-wide and not just the corpus: §8.3 — the CTE visitor-coverage gap was only ever caught by running over the
real ``test_query.py`` paths, not a hand-picked corpus. A position absent from the corpus can still ship a regression,
so the deletion gate must observe the entire suite.

Run it as a plain script from the repo root (NOT ``python -m`` — that imports the ``posthog.hogql.printer`` package,
which loads Django models, before this module can set Django up)::

    env DJANGO_SETTINGS_MODULE=posthog.settings python posthog/hogql/printer/test/run_reachability_oracle.py [paths...]

The script bootstraps Django itself, so no test runner is required. With no paths it defaults to a sensible HogQL set.
Importing this module does nothing — the run is guarded behind ``if __name__ == "__main__"``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from posthog.hogql.constants import HogQLDialect
    from posthog.hogql.printer.test.reachability_oracle import ReachCollector


def _bootstrap_django() -> None:
    """Make the repo importable and the Django app registry ready before any ``posthog`` import.

    This must run before importing the oracle/printers (they import Django models). Invoking the file by path (rather
    than ``python -m``) keeps the ``posthog.hogql.printer`` package ``__init__`` — which imports models — from running
    until after ``django.setup()``. A no-op if Django is already configured (e.g. imported under pytest).
    """
    repo_root = Path(__file__).resolve().parents[4]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")

    import django  # noqa: PLC0415 — bootstrap import, must follow the sys.path/env setup above
    from django.apps import apps  # noqa: PLC0415

    if not apps.ready:
        django.setup()


# Fixed dialect order so the report groups deterministically. A plain tuple of literals — no posthog import needed at
# module load (the ``HogQLDialect`` alias is only referenced in type positions, under TYPE_CHECKING).
ORDERED_DIALECTS: tuple[HogQLDialect, ...] = ("hogql", "clickhouse", "postgres", "duckdb")

# Default paths: the HogQL printer + transforms tests plus the end-to-end query path. test_query.py is the one that
# surfaced the CTE gap (§3.2/§8.3), so it earns its place in the default set.
DEFAULT_PATHS: tuple[str, ...] = (
    "posthog/hogql/printer/test/",
    "posthog/hogql/transforms/test/",
    "posthog/hogql/test/test_query.py",
)

REPORT_PATH = Path(__file__).parent / "__golden__" / "reachability_baseline.txt"


def run(paths: list[str]) -> tuple[int, ReachCollector]:
    """Run pytest over ``paths`` with the oracle active; return ``(pytest_exit_code, aggregated_collector)``.

    The oracle wraps the printer class methods for the duration of ``pytest.main``; because tests run in this same
    process (no ``-n``), the single collector accumulates reaches from every test the run touched.
    """
    # Deferred: importing the oracle loads the printers (→ Django models); must come after _bootstrap_django().
    import pytest  # noqa: PLC0415

    from posthog.hogql.printer.test.reachability_oracle import printer_reachability_oracle  # noqa: PLC0415

    # ``-q`` trims noise; ``-p no:randomly`` keeps ordering stable. The oracle adds no markers, so the suite runs
    # exactly as it normally would — we only observe.
    pytest_args = ["-p", "no:randomly", "-q", *paths]
    with printer_reachability_oracle() as collector:
        exit_code = pytest.main(pytest_args)
    return int(exit_code), collector


def write_report(collector: ReachCollector) -> Path:
    # Deferred for the same Django-ordering reason as in run().
    from posthog.hogql.printer.test.reachability_oracle import format_report  # noqa: PLC0415

    REPORT_PATH.parent.mkdir(exist_ok=True)
    REPORT_PATH.write_text(format_report(collector, ORDERED_DIALECTS))
    return REPORT_PATH


def main(argv: list[str]) -> int:
    _bootstrap_django()

    # Deferred for the same Django-ordering reason as in run() / write_report().
    from posthog.hogql.printer.test.reachability_oracle import summarize  # noqa: PLC0415

    paths = argv or list(DEFAULT_PATHS)
    # This is a standalone report CLI; printing to stdout is its whole interface (no logger).
    print(f"[reachability-oracle] running pytest over: {' '.join(paths)}", flush=True)  # noqa: T201

    exit_code, collector = run(paths)

    report_path = write_report(collector)

    print("\n" + summarize(collector, ORDERED_DIALECTS), flush=True)  # noqa: T201
    print(f"\n[reachability-oracle] wrote report to {report_path}", flush=True)  # noqa: T201
    print(f"[reachability-oracle] pytest exit code: {exit_code}", flush=True)  # noqa: T201

    # The runner's own success is "did the oracle run and write its report" — surfaced via the pytest exit code so a
    # broken suite is visible, but the report is written regardless (a partial run still captures real reaches).
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
