import dagster

from posthog.dags import (
    delete_persons_from_trigger_log,
    ingestion_assets,
    person_property_reconciliation,
    persondistinctids_without_person_cleanup,
    persons_new_backfill,
    persons_without_distinct_ids_cleanup,
)

from . import resources

defs = dagster.Definitions(
    assets=[
        ingestion_assets.postgres_env_check,
    ],
    jobs=[
        delete_persons_from_trigger_log.delete_persons_from_trigger_log_job,
        person_property_reconciliation.person_property_reconciliation_job,
        persondistinctids_without_person_cleanup.persondistinctids_without_person_cleanup_job,
        persons_new_backfill.persons_new_backfill_job,
        persons_without_distinct_ids_cleanup.persons_without_distinct_ids_cleanup_job,
    ],
    sensors=[
        person_property_reconciliation.person_property_reconciliation_scheduler,
    ],
    resources=resources,
)
