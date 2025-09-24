"""
Experiment metric fingerprinting

Generates fingerprints for experiment metrics to detect when metric definitions
or the experiment itself have changed in ways that would affect calculation results.
Used to invalidate cached timeseries data when metrics are modified.
"""

import json
import hashlib
from copy import deepcopy
from datetime import datetime
from typing import Any

METRIC_FIELDS_TO_IGNORE: set[str] = {
    "uuid",
    "name",
    "kind",
    "fingerprint",
}


def compute_metric_fingerprint(
    metric: dict, start_date: Any, stats_config: dict | None, exposure_criteria: dict | None
) -> str:
    """
    Compute fingerprint for a metric.

    Args:
        metric: The metric definition
        start_date: Experiment start date
        stats_config
        exposure_criteria

    Returns:
        SHA256 hash string representing the metric fingerprint
    """
    clean_metric = deepcopy(metric)
    for field in METRIC_FIELDS_TO_IGNORE:
        clean_metric.pop(field, None)

    # Convert datetime to ISO string for JSON serialization
    start_date_str = start_date.isoformat() if isinstance(start_date, datetime) else start_date

    fingerprint_data = {
        "metric": clean_metric,
        "experiment": {
            "start_date": start_date_str,
            "stats_config": stats_config,
        },
    }

    if exposure_criteria:
        fingerprint_data["exposure_criteria"] = exposure_criteria

    # Create deterministic JSON string with sorted keys at all levels
    json_str = json.dumps(fingerprint_data, sort_keys=True, separators=(",", ":"))

    hash_result = hashlib.sha256(json_str.encode("utf-8")).hexdigest()

    return hash_result
