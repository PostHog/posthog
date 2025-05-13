from typing import Literal, get_args


## API Scopes
# These are the scopes that are used to define the permissions of the API tokens.
# Not every model needs a scope - it should more be for top-level things
# Typically each object should have `read` and `write` scopes, but some objects may have more specific scopes

# WARNING: Make sure to keep in sync with the frontend!
APIScopeObject = Literal[
    "action",
    "activity_log",
    "annotation",
    "batch_export",
    "cohort",
    "dashboard",
    "dashboard_template",
    "early_access_feature",
    "error_tracking",
    "event_definition",
    "experiment",
    "export",
    "feature_flag",
    "file_system",
    "file_system_shortcut",
    "group",
    "hog_function",
    "insight",
    "notebook",
    "organization",
    "organization_member",
    "person",
    "plugin",
    "project",
    "property_definition",
    "query",  # Covers query and events endpoints
    "session_recording",
    "session_recording_playlist",
    "sharing_configuration",
    "subscription",
    "survey",
    "user",
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
