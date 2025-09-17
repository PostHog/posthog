from posthog.temporal.delete_persons.delete_persons_workflow import (
    DeletePersonsWorkflow,
    delete_persons_activity,
    mogrify_delete_queries_activity,
)

WORKFLOWS = [
    DeletePersonsWorkflow,
]

ACTIVITIES = [
    delete_persons_activity,
    mogrify_delete_queries_activity,
]
