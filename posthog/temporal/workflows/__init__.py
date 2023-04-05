from posthog.temporal.workflows.noop import *
from typing import Callable, Sequence

from posthog.temporal.workflows.squash_person_overrides import *

WORKFLOWS = [NoOpWorkflow, SquashPersonOverridesWorkflow]
ACTIVITIES: Sequence[Callable] = [
    noop_activity,
    prepare_join_table,
    select_persons_to_delete,
    squash_events_partition,
    drop_join_table,
    delete_squashed_person_overrides_from_clickhouse,
    delete_squashed_person_overrides_from_postgres,
]
