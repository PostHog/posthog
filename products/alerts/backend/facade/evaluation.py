"""Threshold comparison for other products to reuse.

`evaluate_threshold` is the one place that decides whether a value is out of bounds, so an adopter
that compares a measured number against a threshold (a signals report check, for instance) words a
breach the same way an insight alert does. The series types are the input shape it expects.
"""

from products.alerts.backend.evaluation.comparator import evaluate_threshold
from products.alerts.backend.evaluation.contract import ComparableSeries, ExtractionResult, SeriesPoint

__all__ = ["ComparableSeries", "ExtractionResult", "SeriesPoint", "evaluate_threshold"]
