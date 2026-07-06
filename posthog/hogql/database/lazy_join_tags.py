# Resolver tags. A LazyJoin stores one of these (plus JSON-able `resolver_params`) instead of
# a Python closure, so a join is described as plain, serializable data. The tag → implementation
# mapping lives in `lazy_join_registry.RESOLVERS` — every supported tag must be listed there.
# This module is import-dependency-free so any module can reference tags without import cycles.
FOREIGN_KEY = "foreign_key"
DATA_WAREHOUSE = "data_warehouse"
DATA_WAREHOUSE_EXPERIMENTS = "data_warehouse_experiments"

PERSONS = "persons"
PERSONS_PDI = "persons_pdi"
PERSON_DISTINCT_IDS = "person_distinct_ids"
PERSON_DISTINCT_ID_OVERRIDES = "person_distinct_id_overrides"
GROUP_N = "group_n"
GROUPS_REVENUE_ANALYTICS = "groups_revenue_analytics"
PERSONS_REVENUE_ANALYTICS = "persons_revenue_analytics"
EVENTS_TO_SESSIONS_V1 = "events_to_sessions_v1"
EVENTS_TO_SESSIONS_V2 = "events_to_sessions_v2"
EVENTS_TO_SESSIONS_V3 = "events_to_sessions_v3"
REPLAY_TO_SESSIONS_V1 = "replay_to_sessions_v1"
REPLAY_TO_SESSIONS_V2 = "replay_to_sessions_v2"
REPLAY_TO_SESSIONS_V3 = "replay_to_sessions_v3"
REPLAY_TO_EVENTS = "replay_to_events"
REPLAY_TO_CONSOLE_LOGS = "replay_to_console_logs"
ERROR_TRACKING_ISSUE_FINGERPRINT_OVERRIDES = "error_tracking_issue_fingerprint_overrides"
ERROR_TRACKING_FINGERPRINT_ISSUE_STATE = "error_tracking_fingerprint_issue_state"
ACCOUNT_TAGS = "account_tags"
ACCOUNT_NOTEBOOKS = "account_notebooks"
ACCOUNT_CUSTOM_PROPERTIES = "account_custom_properties"
