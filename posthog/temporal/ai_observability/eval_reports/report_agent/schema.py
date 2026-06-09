"""Dataclasses for evaluation report content, metrics, and citations.

The v2 schema splits the report into:
- `metrics`: structured numeric data computed mechanically from ClickHouse,
  the agent cannot fabricate these
- `title`: the agent's punchline headline (required, one line)
- `sections`: 1-6 agent-chosen titled markdown sections
- `citations`: structured trace references (generation_id + trace_id + reason)

This separation lets downstream consumers (signals, inbox, coding agents) query
`metrics` and `citations` without parsing prose, and lets the agent focus on
analysis rather than number formatting.
"""

from dataclasses import dataclass, field

# Hard cap on the number of agent-chosen sections. Prevents section sprawl and
# keeps reports scannable. The agent is also instructed to lean lean — quality
# over quantity, merge related findings rather than fragmenting.
MAX_REPORT_SECTIONS = 6
MIN_REPORT_SECTIONS = 1


@dataclass
class Citation:
    """A trace reference cited by the agent to ground a specific finding.

    Stores both generation_id and trace_id up front so the viewer can construct
    correct trace URLs without a runtime lookup. `reason` is short free-form
    text (e.g. "high_cost", "refusal", "regression_14:00") the agent uses to
    categorize why the trace is interesting.
    """

    generation_id: str
    trace_id: str
    reason: str

    def to_dict(self) -> dict:
        return {
            "generation_id": self.generation_id,
            "trace_id": self.trace_id,
            "reason": self.reason,
        }

    @staticmethod
    def from_dict(data: dict) -> "Citation":
        return Citation(
            generation_id=data.get("generation_id", ""),
            trace_id=data.get("trace_id", ""),
            reason=data.get("reason", ""),
        )


@dataclass
class ReportSection:
    """A titled markdown section of the narrative. Title is agent-chosen."""

    title: str
    content: str

    def to_dict(self) -> dict:
        return {"title": self.title, "content": self.content}

    @staticmethod
    def from_dict(data: dict) -> "ReportSection":
        return ReportSection(
            title=data.get("title", ""),
            content=data.get("content", ""),
        )


@dataclass
class EvalReportMetrics:
    """Structured metrics computed mechanically from ClickHouse.

    The agent cannot write these — they come from `_compute_metrics` in graph.py
    after the agent finishes. Keep this list intentionally small and obvious
    to avoid confusion; per-model/per-bucket/cost breakdowns are deferred.
    """

    total_runs: int = 0
    pass_count: int = 0
    fail_count: int = 0
    na_count: int = 0
    pass_rate: float = 0.0
    period_start: str = ""
    period_end: str = ""
    previous_total_runs: int | None = None
    previous_pass_rate: float | None = None

    def to_dict(self) -> dict:
        return {
            "total_runs": self.total_runs,
            "pass_count": self.pass_count,
            "fail_count": self.fail_count,
            "na_count": self.na_count,
            "pass_rate": self.pass_rate,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "previous_total_runs": self.previous_total_runs,
            "previous_pass_rate": self.previous_pass_rate,
        }

    @staticmethod
    def from_dict(data: dict) -> "EvalReportMetrics":
        return EvalReportMetrics(
            total_runs=data.get("total_runs", 0),
            pass_count=data.get("pass_count", 0),
            fail_count=data.get("fail_count", 0),
            na_count=data.get("na_count", 0),
            pass_rate=data.get("pass_rate", 0.0),
            period_start=data.get("period_start", ""),
            period_end=data.get("period_end", ""),
            previous_total_runs=data.get("previous_total_runs"),
            previous_pass_rate=data.get("previous_pass_rate"),
        )


@dataclass
class EvalReportContent:
    """Top-level report content. Stored in EvaluationReportRun.content JSONField."""

    title: str = ""
    sections: list[ReportSection] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    metrics: EvalReportMetrics = field(default_factory=EvalReportMetrics)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "sections": [s.to_dict() for s in self.sections],
            "citations": [c.to_dict() for c in self.citations],
            "metrics": self.metrics.to_dict(),
        }

    @staticmethod
    def from_dict(data: dict) -> "EvalReportContent":
        return EvalReportContent(
            title=data.get("title", ""),
            sections=[ReportSection.from_dict(s) for s in data.get("sections", [])],
            citations=[Citation.from_dict(c) for c in data.get("citations", [])],
            metrics=EvalReportMetrics.from_dict(data.get("metrics", {})),
        )
