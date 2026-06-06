from temporalio.common import SearchAttributeKey

# Custom search attributes are capped per type per Temporal Cloud namespace:
#   Bool: 20, Datetime: 20, Double: 20, Int: 20, Keyword: 40, KeywordList: 5, Text: 5
#   https://docs.temporal.io/cloud/limits#number-of-custom-search-attributes
# Adding a new custom search attribute to production namespaces is a manual process
# that requires the Namespace Admin role in Temporal Cloud. Be mindful when adding new ones.
# Deleting custom search attributes has to go through their support. You've been warned.

POSTHOG_TEAM_ID_KEY = SearchAttributeKey.for_int("PostHogTeamId")
POSTHOG_ORG_ID_KEY = SearchAttributeKey.for_keyword("PostHogOrgId")
# Data modeling
POSTHOG_DAG_ID_KEY = SearchAttributeKey.for_keyword("PostHogDagId")
# Tags a Temporal schedule so a namespace-wide reconciler can find its own schedules
# without scanning every schedule in the namespace.
POSTHOG_SCHEDULE_TYPE_KEY = SearchAttributeKey.for_keyword("PostHogScheduleType")
# Hash of the SignalSourceConfig dict that produced the schedule. Reconcilers
# compare to the freshly-computed hash to detect drift after UI config edits.
POSTHOG_SCHEDULE_FINGERPRINT_KEY = SearchAttributeKey.for_keyword("PostHogScheduleFingerprint")
POSTHOG_SESSION_RECORDING_ID_KEY = SearchAttributeKey.for_keyword("PostHogSessionRecordingId")

# Registry of all custom search attributes PostHog registers in Temporal.
# This is the single source of truth — the register_temporal_search_attributes
# management command reads from this list.
POSTHOG_SEARCH_ATTRIBUTES: list[SearchAttributeKey] = [
    POSTHOG_TEAM_ID_KEY,
    POSTHOG_ORG_ID_KEY,
    POSTHOG_DAG_ID_KEY,
    POSTHOG_SCHEDULE_TYPE_KEY,
    POSTHOG_SCHEDULE_FINGERPRINT_KEY,
    POSTHOG_SESSION_RECORDING_ID_KEY,
]
