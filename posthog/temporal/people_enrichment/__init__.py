from posthog.temporal.people_enrichment.workflow import (
    PeopleEnrichmentWorkflow,
    count_targets_activity,
    enrich_people_chunk_activity,
)

WORKFLOWS = [PeopleEnrichmentWorkflow]

ACTIVITIES = [count_targets_activity, enrich_people_chunk_activity]
