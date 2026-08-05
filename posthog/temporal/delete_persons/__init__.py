from posthog.temporal.delete_persons.delete_persons_workflow import (
    DeletePersonsWorkflow,
    delete_persons_activity,
    preclean_cohort_members_activity,
)

WORKFLOWS = [
    DeletePersonsWorkflow,
]

ACTIVITIES = [
    delete_persons_activity,
    preclean_cohort_members_activity,
]
