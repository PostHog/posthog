from typing import Any


def series_label(row: dict[str, Any]) -> str:
    """The name of one metrics result series in breach messages and threshold suggestions."""
    name = row.get("metricName") or row.get("clause") or "metric"
    labels = row.get("labels") or {}
    if labels:
        rendered = ", ".join(f"{key}={value}" for key, value in sorted(labels.items()))
        return f"{name} {{{rendered}}}"
    return str(name)
