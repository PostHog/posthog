from posthog.temporal.sync_person_distinct_ids.activities import (
    find_orphaned_persons,
    lookup_pg_distinct_ids,
    mark_ch_only_orphans_deleted,
    sync_distinct_ids_to_ch,
)
from posthog.temporal.sync_person_distinct_ids.workflow import SyncPersonDistinctIdsWorkflow

WORKFLOWS = [
    SyncPersonDistinctIdsWorkflow,
]

ACTIVITIES = [
    find_orphaned_persons,
    lookup_pg_distinct_ids,
    sync_distinct_ids_to_ch,
    mark_ch_only_orphans_deleted,
]
