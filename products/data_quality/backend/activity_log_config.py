FIELD_EXCLUSIONS = {
    "DataQualityCheck": [
        # Written by the runner, not by a person editing the check.
        "last_run_at",
        "last_status",
        "subject_name",
        "subject_status",
        "failing_since",
        "last_succeeded_at",
        # Subject FKs are immutable after create and not JSON-serializable for the change detail.
        "metric",
        "saved_query",
        "table",
    ],
}


SIGNAL_EXCLUSIONS = {
    # Written by the runner on every run, not by a person editing the check.
    "DataQualityCheck": [
        "last_run_at",
        "last_status",
        "subject_name",
        "subject_status",
        "failing_since",
        "last_succeeded_at",
        "updated_at",
    ],
}
