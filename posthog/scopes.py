from typing import Literal, get_args

## API Scopes
# These are the scopes that are used to define the permissions of the API tokens.
# Not every model needs a scope - it should more be for top-level things
# Typically each object should have `read` and `write` scopes, but some objects may have more specific scopes

# WARNING: Make sure to keep in sync with the frontend!
APIScopeObject = Literal[
    "action",
    "access_control",
    "activity_log",
    "annotation",
    "batch_export",
    "batch_import",
    "cohort",
    "dashboard",
    "dashboard_template",
    "dataset",
    "desktop_recording",
    "early_access_feature",
    "endpoint",
    "error_tracking",
    "evaluation",
    "event_definition",
    "experiment",
    "export",
    "feature_flag",
    "file_system",
    "file_system_shortcut",
    "group",
    "hog_function",
    "insight",
    "integration",
    "link",
    "live_debugger",
    "logs",
    "notebook",
    "organization",
    "organization_member",
    "person",
    "persisted_folder",
    "plugin",
    "project",
    "property_definition",
    "query",  # Covers query and events endpoints
    "revenue_analytics",
    "session_recording",
    "session_recording_playlist",
    "sharing_configuration",
    "subscription",
    "survey",
    "task",
    "user",
    "user_interview_DO_NOT_USE",  # This is a super alpha product, so only exposing here for internal personal API key access
    "warehouse_table",
    "warehouse_view",
    "web_analytics",
    "webhook",
]

APIScopeActions = Literal[
    "read",
    "write",
]

APIScopeObjectOrNotSupported = Literal[
    APIScopeObject,
    "INTERNAL",
]

API_SCOPE_OBJECTS: tuple[APIScopeObject, ...] = get_args(APIScopeObject)
API_SCOPE_ACTIONS: tuple[APIScopeActions, ...] = get_args(APIScopeActions)


def get_scope_descriptions() -> dict[str, str]:
    return {
        f"{obj}:{action}": f"{action.capitalize()} access to {obj}"
        for obj in API_SCOPE_OBJECTS
        for action in API_SCOPE_ACTIONS
    }
