from posthog.tasks.alerts.detectors.statistical.iqr import IQRDetector
from posthog.tasks.alerts.detectors.statistical.mad import MADDetector
from posthog.tasks.alerts.detectors.statistical.zscore import ZScoreDetector

__all__ = ["ZScoreDetector", "MADDetector", "IQRDetector"]
