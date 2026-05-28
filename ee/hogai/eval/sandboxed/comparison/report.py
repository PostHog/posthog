"""Aggregate per-run comparison results into a markdown + JSON report.

Pure data layer — no harness/Django deps — so it's unit-testable and the blog
table can be regenerated from a saved results JSON without re-running anything.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from statistics import mean


@dataclass
class RunResult:
    """One (arm, task, repetition) run."""

    arm: str
    task: str
    rep: int
    total_tokens: int
    input_tokens: int
    output_tokens: int
    cached_tokens: int
    duration_seconds: float
    outcome_pass: bool | None  # deterministic DB/state assertion (None = not applicable)
    judge_pass: bool | None  # LLM-judge on the final answer (None = not run)
    exit_code: int


@dataclass
class ArmSummary:
    arm: str
    runs: int
    mean_total_tokens: float
    mean_input_tokens: float
    mean_output_tokens: float
    mean_cached_tokens: float
    mean_duration_seconds: float
    outcome_success_rate: float | None
    judge_success_rate: float | None
    error_rate: float


def _rate(values: list[bool | None]) -> float | None:
    present = [v for v in values if v is not None]
    if not present:
        return None
    return sum(1 for v in present if v) / len(present)


def summarize(results: list[RunResult]) -> dict[str, ArmSummary]:
    """Aggregate per arm, preserving first-seen arm order."""
    by_arm: dict[str, list[RunResult]] = {}
    for r in results:
        by_arm.setdefault(r.arm, []).append(r)

    summaries: dict[str, ArmSummary] = {}
    for arm, runs in by_arm.items():
        summaries[arm] = ArmSummary(
            arm=arm,
            runs=len(runs),
            mean_total_tokens=mean(r.total_tokens for r in runs),
            mean_input_tokens=mean(r.input_tokens for r in runs),
            mean_output_tokens=mean(r.output_tokens for r in runs),
            mean_cached_tokens=mean(r.cached_tokens for r in runs),
            mean_duration_seconds=mean(r.duration_seconds for r in runs),
            outcome_success_rate=_rate([r.outcome_pass for r in runs]),
            judge_success_rate=_rate([r.judge_pass for r in runs]),
            error_rate=sum(1 for r in runs if r.exit_code != 0) / len(runs),
        )
    return summaries


def _fmt_pct(rate: float | None) -> str:
    return "n/a" if rate is None else f"{rate * 100:.0f}%"


def render_markdown(results: list[RunResult], *, title: str = "CLI vs MCP comparison") -> str:
    """Render a blog-ready markdown table. The first arm is treated as the baseline
    for the relative-token column (e.g. CLI vs each MCP mode)."""
    summaries = summarize(results)
    if not summaries:
        return f"# {title}\n\n(no results)\n"

    arms = list(summaries.values())
    baseline = arms[0].mean_total_tokens or 1.0

    lines = [
        f"# {title}",
        "",
        f"Tasks: {len({r.task for r in results})} · repetitions/arm: "
        f"{max((s.runs for s in arms), default=0) // max(len({r.task for r in results}), 1)} · "
        f"single-task sessions (MCP tools-mode upfront cost not amortized).",
        "",
        "| Arm | Runs | Mean tokens | vs baseline | Mean input | Mean output | Mean cached | "
        "Mean time (s) | Outcome ✓ | Judge ✓ | Errors |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for s in arms:
        rel = s.mean_total_tokens / baseline
        lines.append(
            f"| {s.arm} | {s.runs} | {s.mean_total_tokens:,.0f} | {rel:.2f}× | "
            f"{s.mean_input_tokens:,.0f} | {s.mean_output_tokens:,.0f} | {s.mean_cached_tokens:,.0f} | "
            f"{s.mean_duration_seconds:.1f} | {_fmt_pct(s.outcome_success_rate)} | "
            f"{_fmt_pct(s.judge_success_rate)} | {_fmt_pct(s.error_rate)} |"
        )
    lines.append("")
    return "\n".join(lines)


def render_json(results: list[RunResult]) -> str:
    return json.dumps(
        {
            "runs": [asdict(r) for r in results],
            "summary": {arm: asdict(s) for arm, s in summarize(results).items()},
        },
        indent=2,
    )


@dataclass
class ReportPaths:
    markdown: str = ""
    json: str = ""
    written: list[str] = field(default_factory=list)
