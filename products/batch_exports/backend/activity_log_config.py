FIELD_EXCLUSIONS = {
    "BatchExport": [
        "latest_runs",
        "last_updated_at",
        "last_paused_at",
        "batchexportrun_set",
        "batchexportbackfill_set",
    ],
}


FIELD_NAME_OVERRIDES = {
    "BatchExport": {
        "paused": "enabled",
    },
}
