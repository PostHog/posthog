from __future__ import annotations

import os
import asyncio
import traceback
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from braintrust.framework import EvalResultWithSummary, Evaluator, ReporterDef
from braintrust.logger import ExperimentSummary

EVAL_RESULTS_JSONL = "eval_results.jsonl"
"""Machine-readable per-experiment summary export, opt-in via ``EXPORT_EVAL_RESULTS``."""

POSTHOG_EVALUATIONS_URL = (
    "https://us.posthog.com/project/2/ai-evals/evaluations/offline/experiments/{experiment_id}?offline_date_from=-1d"
)


def _emit(text: str) -> None:
    print(text)  # noqa: T201 — this module is the single owner of harness terminal output


@dataclass
class SuiteRunResult:
    """Outcome of one suite function, assembled by the orchestrator.

    Carries only the crash and timing information the reporter cannot observe on
    its own. Case counts, per-scorer scores, and the Braintrust URL all live on
    the summaries the reporter collects via ``record_summary``.
    """

    suite_id: str
    status: Literal["passed", "crashed"]
    error: BaseException | None = None
    duration_seconds: float = 0.0


class ProgressReporter:
    """Serializes every line the harness prints and owns the results export.

    Suites run concurrently on one event loop, so their Braintrust score dumps
    and log lines would otherwise interleave into noise. Every terminal write
    goes through one ``asyncio.Lock``; the machine-readable JSONL export shares
    the same lock so concurrent appends can't tear a line in half.
    """

    def __init__(self, total_suites: int) -> None:
        self._total_suites = total_suites
        self._lock = asyncio.Lock()
        self._finished_suites = 0
        # Insertion-ordered so the final table reads in the order suites completed.
        self._summaries: dict[str, ExperimentSummary] = {}
        self._case_counts: dict[str, int] = defaultdict(int)
        self._case_durations: dict[str, float] = defaultdict(float)
        self._error_counts: dict[str, int] = defaultdict(int)
        # Planned case total per experiment (post-filter, times trials), used to
        # render a per-experiment progress counter on each case line.
        self._experiment_totals: dict[str, int] = {}

    async def suite_started(self, suite_id: str) -> None:
        async with self._lock:
            _emit(f"{self._counter()} START  {suite_id}")

    async def experiment_started(self, experiment_name: str, planned_cases: int) -> None:
        """Record how many cases this experiment will run, so ``case_done`` can
        show a ``[done/total]`` counter. Suites register concurrently, so this
        takes the lock even though it only writes."""
        async with self._lock:
            self._experiment_totals[experiment_name] = planned_cases

    async def case_done(
        self,
        experiment_name: str,
        case_name: str,
        *,
        duration_seconds: float,
        status: Literal["ok", "timeout", "error"] = "ok",
    ) -> None:
        """Keyed by experiment rather than suite id: a case only knows which
        Braintrust experiment it belongs to, and that is what the table rows are.

        ``status`` distinguishes a normal finish from a timeout (scored 0) or an
        infra error (excluded from scores) so the two stand out in the live stream."""
        async with self._lock:
            self._case_counts[experiment_name] += 1
            self._case_durations[experiment_name] += duration_seconds
            marker = {"ok": "case ", "timeout": "TMOUT", "error": "ERROR"}[status]
            # Per-experiment case counter, distinct from the suite counter prefix;
            # omitted when the experiment was never registered.
            total = self._experiment_totals.get(experiment_name)
            progress = f"  [{self._case_counts[experiment_name]}/{total}]" if total is not None else ""
            _emit(f"{self._counter()} {marker}  {experiment_name} :: {case_name}  ({duration_seconds:.1f}s){progress}")

    async def case_log_path(self, case_name: str, path: Path) -> None:
        async with self._lock:
            _emit(f"[eval-logs] {case_name}: {path}")

    async def suite_finished(self, result: SuiteRunResult) -> None:
        async with self._lock:
            self._finished_suites += 1
            marker = "PASS " if result.status == "passed" else "CRASH"
            _emit(f"{self._counter()} {marker}  {result.suite_id}  ({result.duration_seconds:.1f}s)")

    async def record_summary(self, experiment_name: str, summary: ExperimentSummary, *, error_count: int = 0) -> None:
        """Store a Braintrust experiment summary for the final table and export it.

        Suite functions do not return their Braintrust result up to the
        orchestrator, so the reporter is the single place both the summary
        table and the JSONL export can read from.

        ``error_count`` is the number of cases Braintrust recorded as errored
        (infra failures excluded from the scores), surfaced in the final table.
        """
        async with self._lock:
            self._summaries[experiment_name] = summary
            self._error_counts[experiment_name] = error_count
            if os.getenv("EXPORT_EVAL_RESULTS"):
                with open(EVAL_RESULTS_JSONL, "a") as f:
                    f.write(summary.as_json() + "\n")

    async def posthog_evaluations_url(self, experiment_id: str) -> None:
        async with self._lock:
            _emit(f"\nPostHog evaluations: {POSTHOG_EVALUATIONS_URL.format(experiment_id=experiment_id)}\n")

    def print_final_summary(self, results: Sequence[SuiteRunResult], log_dirs: set[Path]) -> None:
        """Render the end-of-run table, raw-log locations, and crash tracebacks.

        Runs after every suite has settled, so it takes no lock. One row per
        recorded experiment, then one row per crashed suite (which never
        produced a summary).
        """
        crashed = [r for r in results if r.status == "crashed"]
        name_width = self._name_column_width(crashed)

        lines: list[str] = ["", _sep("sandboxed eval summary")]
        for experiment_name, summary in self._summaries.items():
            lines.extend(self._passed_rows(experiment_name, summary, name_width))
        for result in crashed:
            lines.extend(self._crashed_rows(result, name_width))
        if not self._summaries and not crashed:
            lines.append("No experiments ran.")

        lines.extend(self._log_dir_block(log_dirs))
        lines.extend(self._traceback_block(crashed))
        _emit("\n".join(lines))

    def mean_score(self) -> float | None:
        """Unweighted mean over every per-scorer average across all recorded
        summaries, or ``None`` when no scores were produced.

        Runs after every suite has settled (like ``print_final_summary``), so it
        takes no lock. Every scorer average counts once, regardless of how many
        cases fed it, matching how the final table reads."""
        scores = [
            s.score for summary in self._summaries.values() for s in summary.scores.values() if s.score is not None
        ]
        if not scores:
            return None
        return sum(scores) / len(scores)

    def print_line(self, text: str) -> None:
        """Emit one line through the reporter. For post-settle callers (no lock),
        so stdout ownership stays with this module instead of leaking bare prints."""
        _emit(text)

    def _counter(self) -> str:
        return f"[{self._finished_suites}/{self._total_suites}]"

    def _name_column_width(self, crashed: Sequence[SuiteRunResult]) -> int:
        names = [*self._summaries.keys(), *(r.suite_id for r in crashed)]
        return min(max((len(name) for name in names), default=0), 60)

    def _passed_rows(self, experiment_name: str, summary: ExperimentSummary, name_width: int) -> list[str]:
        case_count = self._case_counts.get(experiment_name, 0)
        duration = self._case_durations.get(experiment_name, 0.0)
        error_count = self._error_counts.get(experiment_name, 0)
        errored = f", {error_count} errored" if error_count else ""
        rows = [f"PASS   {experiment_name:<{name_width}}  {case_count:>3} cases{errored}  {duration:>7.1f}s"]
        scores = "  ".join(f"{name} {s.score * 100:.1f}%" for name, s in summary.scores.items() if s.score is not None)
        if scores:
            rows.append(f"         scores: {scores}")
        rows.append(f"         url:    {summary.experiment_url or '(local run, no Braintrust experiment)'}")
        return rows

    def _crashed_rows(self, result: SuiteRunResult, name_width: int) -> list[str]:
        rows = [f"CRASH  {result.suite_id:<{name_width}}  {'':>3}        {result.duration_seconds:>7.1f}s"]
        if result.error is not None:
            rows.append(f"         error:  {type(result.error).__name__}: {result.error}")
        return rows

    def _log_dir_block(self, log_dirs: set[Path]) -> list[str]:
        if not log_dirs:
            return []
        lines = ["", _sep("sandboxed eval logs"), "Raw agent logs written to:"]
        lines.extend(f"  {path}" for path in sorted(log_dirs))
        lines.append("Files per case: <case>.jsonl (raw), <case>.artifacts.json, <case>.summary.txt")
        return lines

    def _traceback_block(self, crashed: Sequence[SuiteRunResult]) -> list[str]:
        if not crashed:
            return []
        lines = ["", _sep("crashed suites")]
        for result in crashed:
            lines.append(f"--- {result.suite_id} ---")
            if result.error is not None:
                lines.append("".join(traceback.format_exception(result.error)).rstrip())
            else:
                lines.append("(no traceback captured)")
        return lines


def _sep(title: str) -> str:
    return f"{'=' * 26} {title} {'=' * 26}"


def _quiet_report_eval(evaluator: Evaluator, result: EvalResultWithSummary, verbose: bool, jsonl: bool) -> bool:
    # Braintrust calls this per experiment to dump the score table. The harness
    # renders its own combined table instead, so this stays silent.
    return True


def _quiet_report_run(results: list[bool], verbose: bool, jsonl: bool) -> bool:
    return True


QUIET_REPORTER: ReporterDef = ReporterDef(
    name="quiet",
    report_eval=_quiet_report_eval,
    report_run=_quiet_report_run,
)
"""Reporter that prints nothing, so concurrent experiments don't dump interleaved
score tables into the shared stdout. All per-run output goes through
``ProgressReporter`` instead."""
