from temporalio import activity
from temporalio.common import MetricCounter, MetricHistogram


def get_feature_flag_sync_finished_metric(status: str) -> MetricCounter:
    """Counter for feature flag sync completion status."""
    return (
        activity.metric_meter()
        .with_additional_attributes({"status": status})
        .create_counter(
            "feature_flag_sync_finished",
            "Number of feature flag sync runs finished, for any reason (including failure).",
        )
    )


def get_feature_flag_sync_duration_metric() -> MetricHistogram:
    """Histogram for feature flag sync execution duration."""
    return activity.metric_meter().create_histogram(
        "feature_flag_sync_duration_seconds", "Histogram tracking execution duration for feature flag sync workflows."
    )


def get_feature_flag_sync_events_processed_metric() -> MetricCounter:
    """Counter for total events processed during sync."""
    return activity.metric_meter().create_counter(
        "feature_flag_sync_events_processed", "Number of feature flag events processed during sync."
    )


def get_feature_flag_sync_flags_updated_metric() -> MetricCounter:
    """Counter for total flags updated during sync."""
    return activity.metric_meter().create_counter(
        "feature_flag_sync_flags_updated", "Number of feature flags updated with last_called_at timestamps."
    )
