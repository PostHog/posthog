from datetime import datetime

from posthog.models import Team

from products.alerts.backend.anomaly_scoring.scoring import INTERVAL_STEP, InsightScores
from products.metrics.backend.facade.api import write_gauges
from products.metrics.backend.facade.contracts import GaugeSample, GaugeWriteResult

SERVICE_NAME = "posthog-insight-anomalies"
VALUE_METRIC = "posthog.insight.value"
SCORE_METRIC = "posthog.insight.anomaly_score"
FLAG_METRIC = "posthog.insight.anomaly_flag"


def gauge_samples(insight_id: int, scores: InsightScores) -> list[GaugeSample]:
    """One value gauge per scored bucket, plus a score and flag gauge once the detector has enough history.

    Each point is stamped at its bucket's close, not its start. The capture service only keeps
    timestamps from the last 24 hours, and a daily or weekly bucket start is older than that by
    the time the bucket completes. A reader that wants bucket starts subtracts one interval.
    """
    step = INTERVAL_STEP[scores.interval]
    samples: list[GaugeSample] = []
    for series in scores.series:
        labels = {
            "insight_id": str(insight_id),
            "series": str(series.series_index),
            "series_label": series.label,
            "interval": scores.interval.value,
            "detector_type": scores.detector_type,
            "detector_version": scores.detector_version,
        }
        if series.breakdown_value is not None:
            labels["breakdown_value"] = series.breakdown_value
        for point in series.points:
            timestamp = point.bucket + step
            samples.append(GaugeSample(name=VALUE_METRIC, value=point.value, timestamp=timestamp, labels=labels))
            if point.score is None:
                continue
            samples.append(GaugeSample(name=SCORE_METRIC, value=point.score, timestamp=timestamp, labels=labels))
            samples.append(GaugeSample(name=FLAG_METRIC, value=float(point.flag), timestamp=timestamp, labels=labels))
    return samples


def last_bucket(scores: InsightScores) -> datetime | None:
    buckets = [point.bucket for series in scores.series for point in series.points]
    return max(buckets, default=None)


def emit_scores(*, team: Team, insight_id: int, scores: InsightScores, now: datetime) -> GaugeWriteResult:
    return write_gauges(team=team, samples=gauge_samples(insight_id, scores), service_name=SERVICE_NAME, now=now)
