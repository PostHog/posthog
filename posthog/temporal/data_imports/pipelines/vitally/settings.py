from posthog.warehouse.types import IncrementalField

ENDPOINTS = (
    "Organizations",
    "Accounts",
    "Users",
    "Conversations",
    "Notes",
    "Projects",
    "Tasks",
    "NPS_Responses",
    "Custom_Objects",
)

INCREMENTAL_ENDPOINTS = ()

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
