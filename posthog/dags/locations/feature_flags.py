import dagster

from products.feature_flags.dags import hash_key_override_cleanup

from . import resources

defs = dagster.Definitions(
    assets=[
        hash_key_override_cleanup.hash_key_override_cleanup,
    ],
    jobs=[
        hash_key_override_cleanup.hash_key_override_cleanup_job,
    ],
    schedules=[
        hash_key_override_cleanup.weekly_hash_key_override_cleanup_schedule,
    ],
    resources=resources,
)
