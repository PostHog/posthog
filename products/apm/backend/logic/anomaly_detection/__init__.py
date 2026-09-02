"""Zero-config log volume anomaly detection — pure detector core.

Everything in this package is a pure function over counts: no ClickHouse,
Temporal, or Django imports. The aggregation layer feeds it rollup counts;
the filing layer persists its verdicts. This separation is what lets the
validation harness (validation/) exercise the risky band math in-process.
"""

from products.apm.backend.logic.anomaly_detection.config import DetectionConfig
from products.apm.backend.logic.anomaly_detection.detector import evaluate_series_bucket, evaluate_tick
from products.apm.backend.logic.anomaly_detection.issues import IssueSnapshot, evaluate_issue_transition
from products.apm.backend.logic.anomaly_detection.types import BucketVerdict, SeriesHistory, SeriesKey, VerdictType

__all__ = [
    "BucketVerdict",
    "DetectionConfig",
    "IssueSnapshot",
    "SeriesHistory",
    "SeriesKey",
    "VerdictType",
    "evaluate_issue_transition",
    "evaluate_series_bucket",
    "evaluate_tick",
]
