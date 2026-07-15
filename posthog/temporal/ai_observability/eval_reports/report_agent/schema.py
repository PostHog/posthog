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
from typing import Literal, overload

from posthog.temporal.ai_observability.eval_reports.output_types import get_outcome_definition

# Hard cap on the number of agent-chosen sections. Prevents section sprawl and
# keeps reports scannable. The agent is also instructed to lean lean — quality
# over quantity, merge related findings rather than fragmenting.
MAX_REPORT_SECTIONS = 6
MIN_REPORT_SECTIONS = 1


def normalize_result_counts(output_type: str, counts: dict[str, int] | None) -> dict[str, int]:
    definition = get_outcome_definition(output_type)
    source = counts or {}
    return {outcome: int(source.get(outcome, 0)) for outcome in definition.outcomes}


def calculate_result_rates(
    output_type: str,
    counts: dict[str, int],
    *,
    empty_as_none: bool = False,
) -> dict[str, float] | None:
    normalized_counts = normalize_result_counts(output_type, counts)
    result_count = sum(normalized_counts.values())
    if result_count == 0:
        return None if empty_as_none else dict.fromkeys(normalized_counts, 0.0)
    return {outcome: round(count / result_count * 100, 2) for outcome, count in normalized_counts.items()}


@overload
def calculate_boolean_pass_rate(counts: dict[str, int], *, empty_as_none: Literal[False] = False) -> float: ...


@overload
def calculate_boolean_pass_rate(counts: dict[str, int], *, empty_as_none: Literal[True]) -> float | None: ...


@overload
def calculate_boolean_pass_rate(counts: dict[str, int], *, empty_as_none: bool) -> float | None: ...


def calculate_boolean_pass_rate(counts: dict[str, int], *, empty_as_none: bool = False) -> float | None:
    pass_count = counts.get("pass", 0)
    applicable_count = pass_count + counts.get("fail", 0)
    if applicable_count == 0:
        return None if empty_as_none else 0.0
    return round(pass_count / applicable_count * 100, 2)


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

    output_type: str = "boolean"
    total_runs: int = 0
    result_counts: dict[str, int] = field(default_factory=dict)
    result_rates: dict[str, float] = field(default_factory=dict)
    period_start: str = ""
    period_end: str = ""
    previous_total_runs: int | None = None
    previous_result_counts: dict[str, int] | None = None
    previous_result_rates: dict[str, float] | None = None
    pass_rate: float = field(init=False, default=0.0)
    previous_pass_rate: float | None = None

    def __post_init__(self) -> None:
        definition = get_outcome_definition(self.output_type)
        self.result_counts = normalize_result_counts(self.output_type, self.result_counts)

        if not self.result_rates:
            self.result_rates = calculate_result_rates(self.output_type, self.result_counts) or {}
        else:
            calculated_rates = calculate_result_rates(self.output_type, self.result_counts) or {}
            self.result_rates = {
                outcome: float(self.result_rates.get(outcome, calculated_rates[outcome]))
                for outcome in definition.outcomes
            }

        if self.previous_result_counts is not None:
            self.previous_result_counts = normalize_result_counts(self.output_type, self.previous_result_counts)
        if self.previous_result_rates is None:
            if self.previous_result_counts is not None:
                self.previous_result_rates = calculate_result_rates(
                    self.output_type, self.previous_result_counts, empty_as_none=True
                )
        elif self.previous_result_counts is not None:
            calculated_previous_rates = calculate_result_rates(self.output_type, self.previous_result_counts) or {}
            self.previous_result_rates = {
                outcome: float(self.previous_result_rates.get(outcome, calculated_previous_rates[outcome]))
                for outcome in definition.outcomes
            }
        else:
            self.previous_result_rates = {
                outcome: float(rate)
                for outcome, rate in self.previous_result_rates.items()
                if outcome in definition.outcomes
            }

        if self.output_type == "boolean":
            self.pass_rate = calculate_boolean_pass_rate(self.result_counts)
            if self.previous_result_counts is not None:
                self.previous_pass_rate = calculate_boolean_pass_rate(self.previous_result_counts, empty_as_none=True)
        else:
            self.previous_pass_rate = None

    def to_dict(self) -> dict:
        metrics = {
            "output_type": self.output_type,
            "total_runs": self.total_runs,
            "result_counts": self.result_counts,
            "result_rates": self.result_rates,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "previous_total_runs": self.previous_total_runs,
            "previous_result_counts": self.previous_result_counts,
            "previous_result_rates": self.previous_result_rates,
        }
        if self.output_type == "boolean":
            metrics.update(
                {
                    "pass_rate": self.pass_rate,
                    "previous_pass_rate": self.previous_pass_rate,
                }
            )
        return metrics

    @staticmethod
    def from_dict(data: dict) -> "EvalReportMetrics":
        output_type = data.get("output_type", "boolean")
        result_counts = dict(data.get("result_counts") or {})
        if output_type == "boolean" and "result_counts" not in data:
            result_counts = {
                "pass": data.get("pass_count", 0),
                "fail": data.get("fail_count", 0),
                "na": data.get("na_count", 0),
            }

        metrics = EvalReportMetrics(
            output_type=output_type,
            total_runs=data.get("total_runs", 0),
            result_counts=result_counts,
            result_rates=dict(data.get("result_rates") or {}),
            period_start=data.get("period_start", ""),
            period_end=data.get("period_end", ""),
            previous_total_runs=data.get("previous_total_runs"),
            previous_result_counts=(
                dict(data["previous_result_counts"]) if data.get("previous_result_counts") is not None else None
            ),
            previous_result_rates=(
                dict(data["previous_result_rates"]) if data.get("previous_result_rates") is not None else None
            ),
            previous_pass_rate=data.get("previous_pass_rate"),
        )
        if metrics.output_type == "boolean" and data.get("pass_rate") is not None:
            metrics.pass_rate = float(data["pass_rate"])
        if metrics.output_type == "boolean" and data.get("previous_pass_rate") is not None:
            metrics.previous_pass_rate = float(data["previous_pass_rate"])
        return metrics


_LEGACY_BOOLEAN_COUNT_FIELDS = frozenset({"pass_count", "fail_count", "na_count"})


_KNOWN_METRIC_FIELDS = {
    "output_type",
    "total_runs",
    "result_counts",
    "result_rates",
    "period_start",
    "period_end",
    "previous_total_runs",
    "previous_result_counts",
    "previous_result_rates",
    "pass_rate",
    "previous_pass_rate",
} | _LEGACY_BOOLEAN_COUNT_FIELDS


def _has_result_counts(data: dict) -> bool:
    return isinstance(data.get("result_counts"), dict) or (
        data.get("output_type", "boolean") == "boolean" and bool(_LEGACY_BOOLEAN_COUNT_FIELDS.intersection(data))
    )


def normalize_metrics_payload(data: dict) -> dict:
    """Upgrade stored metrics without turning missing historical values into zero."""
    extensions = {key: value for key, value in data.items() if key not in _KNOWN_METRIC_FIELDS}
    normalized = EvalReportMetrics.from_dict(data).to_dict()

    if not _has_result_counts(data):
        normalized.pop("result_counts", None)
        provided_rates = data.get("result_rates")
        if isinstance(provided_rates, dict):
            normalized_rates = normalized.get("result_rates", {})
            normalized["result_rates"] = {
                outcome: normalized_rates[outcome] for outcome in provided_rates if outcome in normalized_rates
            }
        else:
            normalized.pop("result_rates", None)
        if data.get("pass_rate") is None:
            normalized.pop("pass_rate", None)

    return {**extensions, **normalized}


def normalize_report_content_payload(data: dict) -> dict:
    """Upgrade a stored report at the read/write boundary without mutating it."""
    normalized = dict(data)
    metrics = data.get("metrics")
    if isinstance(metrics, dict):
        normalized["metrics"] = normalize_metrics_payload(metrics)
    return normalized


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
