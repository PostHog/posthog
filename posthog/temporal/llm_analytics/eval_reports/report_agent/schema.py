"""Dataclasses for evaluation report content and metadata."""

from dataclasses import dataclass, field


@dataclass
class ReportSection:
    content: str
    referenced_generation_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "content": self.content,
            "referenced_generation_ids": self.referenced_generation_ids,
        }

    @staticmethod
    def from_dict(data: dict) -> "ReportSection":
        return ReportSection(
            content=data.get("content", ""),
            referenced_generation_ids=data.get("referenced_generation_ids", []),
        )


REPORT_SECTIONS = [
    "executive_summary",
    "statistics",
    "trend_analysis",
    "failure_patterns",
    "pass_patterns",
    "notable_changes",
    "recommendations",
    "risk_assessment",
]


@dataclass
class EvalReportContent:
    executive_summary: ReportSection | None = None
    statistics: ReportSection | None = None
    trend_analysis: ReportSection | None = None
    failure_patterns: ReportSection | None = None
    pass_patterns: ReportSection | None = None
    notable_changes: ReportSection | None = None
    recommendations: ReportSection | None = None
    risk_assessment: ReportSection | None = None

    def to_dict(self) -> dict:
        result = {}
        for section_name in REPORT_SECTIONS:
            section = getattr(self, section_name)
            if section is not None:
                result[section_name] = section.to_dict()
        return result

    @staticmethod
    def from_dict(data: dict) -> "EvalReportContent":
        content = EvalReportContent()
        for section_name in REPORT_SECTIONS:
            if section_name in data and data[section_name] is not None:
                setattr(content, section_name, ReportSection.from_dict(data[section_name]))
        return content


@dataclass
class EvalReportMetadata:
    total_runs: int = 0
    pass_count: int = 0
    fail_count: int = 0
    na_count: int = 0
    pass_rate: float = 0.0
    previous_pass_rate: float | None = None

    def to_dict(self) -> dict:
        return {
            "total_runs": self.total_runs,
            "pass_count": self.pass_count,
            "fail_count": self.fail_count,
            "na_count": self.na_count,
            "pass_rate": self.pass_rate,
            "previous_pass_rate": self.previous_pass_rate,
        }

    @staticmethod
    def from_dict(data: dict) -> "EvalReportMetadata":
        return EvalReportMetadata(
            total_runs=data.get("total_runs", 0),
            pass_count=data.get("pass_count", 0),
            fail_count=data.get("fail_count", 0),
            na_count=data.get("na_count", 0),
            pass_rate=data.get("pass_rate", 0.0),
            previous_pass_rate=data.get("previous_pass_rate"),
        )
