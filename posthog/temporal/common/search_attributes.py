from temporalio.common import SearchAttributeKey

POSTHOG_TEAM_ID_KEY = SearchAttributeKey.for_int("PostHogTeamId")
POSTHOG_ORG_ID_KEY = SearchAttributeKey.for_keyword("PostHogOrgId")
# Data modeling
POSTHOG_DAG_ID_KEY = SearchAttributeKey.for_keyword("PostHogDagId")

# Registry of all custom search attributes PostHog registers in Temporal.
# This is the single source of truth — the register_temporal_search_attributes
# management command reads from this list.
POSTHOG_SEARCH_ATTRIBUTES: list[SearchAttributeKey] = [
    POSTHOG_TEAM_ID_KEY,
    POSTHOG_ORG_ID_KEY,
    POSTHOG_DAG_ID_KEY,
]
