from typing import Callable, Sequence

from posthog.temporal.workflows.noop import *
from posthog.temporal.workflows.squash_person_overrides import *

WORKFLOWS = [NoOpWorkflow, SquashPersonOverridesWorkflow]
ACTIVITIES: Sequence[Callable] = [
    noop_activity,
    prepare_person_overrides,
    prepare_dictionary,
    select_persons_to_delete,
    squash_events_partition,
    drop_dictionary,
    delete_squashed_person_overrides_from_clickhouse,
    delete_squashed_person_overrides_from_postgres,
]
