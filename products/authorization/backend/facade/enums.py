"""
Exported enums for authorization.

If an enum appears in a contract dataclass field, it belongs here.
Internal-only constants (DB magic values, feature flags) stay in
the implementation (logic.py, models.py).

No Django imports: use LabeledStrEnum or LabeledIntEnum, not
models.TextChoices, for an enum that backs model or serializer choices.
"""

from enum import StrEnum


class Action(StrEnum):
    """An operation a subject asks to perform on a resource."""

    VIEW = "view"
    EDIT = "edit"
    DELETE = "delete"
    SHARE = "share"
    MANAGE_ACCESS = "manage_access"
    CREATE = "create"
    QUERY = "query"
    JOIN = "join"
    MANAGE_OWNERS = "manage_owners"
    EDIT_MEMBER_SETTINGS = "edit_member_settings"
    SUPPORT = "support"
    APPROVE = "approve"
    MANAGE_BILLING = "manage_billing"


class Level(StrEnum):
    """A relation a subject holds on a resource, project or organization.

    A level that more than one layer uses has one member here.
    """

    NONE = "none"
    VIEWER = "viewer"
    EDITOR = "editor"
    MANAGER = "manager"
    MEMBER = "member"
    ADMIN = "admin"
    OWNER = "owner"


class ResourceType(StrEnum):
    """A type of resource that access rules can target."""

    ORGANIZATION = "organization"
    PROJECT = "project"
    ROLE = "role"
    # Keep in sync with ACCESS_CONTROL_RESOURCES in products/access_control/backend/facade/user_access_control.py.
    # Also cover every `access_scope` a HogQL PostgresTable declares. These are not in that tuple:
    ACCOUNT = "account"
    ALERT = "alert"
    ANNOTATION = "annotation"
    AUTORESEARCH = "autoresearch"
    BATCH_EXPORT = "batch_export"
    CANVAS = "canvas"
    CUSTOMER_TASK = "customer_task"
    DATASET = "dataset"
    HOG_FUNCTION = "hog_function"
    INTEGRATION = "integration"
    SESSION_RECORDING_PLAYLIST = "session_recording_playlist"
    SIGNAL_SCOUT = "signal_scout"
    TASK = "task"
    USAGE_METRIC = "usage_metric"
    ACTION = "action"
    CUSTOMER_ANALYTICS = "customer_analytics"
    DATA_CATALOG = "data_catalog"
    DATA_DELETION = "data_deletion"
    DASHBOARD = "dashboard"
    EARLY_ACCESS_FEATURE = "early_access_feature"
    ENDPOINT = "endpoint"
    EXPERIMENT = "experiment"
    EXPORT = "export"
    EXTERNAL_DATA_SOURCE = "external_data_source"
    WAREHOUSE_OBJECTS = "warehouse_objects"
    FEATURE_FLAG = "feature_flag"
    HEATMAP = "heatmap"
    HOG_FLOW = "hog_flow"
    INSIGHT = "insight"
    LLM_ANALYTICS = "llm_analytics"
    EVALUATION = "evaluation"
    TAGGER = "tagger"
    LLM_SKILL = "llm_skill"
    AI_OBSERVABILITY_CLUSTERS = "ai_observability_clusters"
    NOTEBOOK = "notebook"
    REVENUE_ANALYTICS = "revenue_analytics"
    SESSION_RECORDING = "session_recording"
    LLM_PROVIDER_KEY = "llm_provider_key"
    LLM_PROMPT = "llm_prompt"
    CUSTOMER_JOURNEY = "customer_journey"
    EXPERIMENT_SAVED_METRIC = "experiment_saved_metric"
    EXPERIMENT_HOLDOUT = "experiment_holdout"
    DASHBOARD_TEMPLATE = "dashboard_template"
    MARKETING_ANALYTICS = "marketing_analytics"
    VISION_ALERT = "vision_alert"
    SHARING_CONFIGURATION = "sharing_configuration"
    STAMPHOG = "stamphog"
    SURVEY = "survey"
    TICKET = "ticket"
    WEB_ANALYTICS = "web_analytics"
    ACTIVITY_LOG = "activity_log"
    BUSINESS_KNOWLEDGE = "business_knowledge"
    ERROR_TRACKING = "error_tracking"
    LOGS = "logs"
    MCP_ANALYTICS = "mcp_analytics"
    METRICS = "metrics"
    TRACING = "tracing"
    REPLAY_SCANNER = "replay_scanner"
    TOOLBAR = "toolbar"
    LLM_PLAYGROUND = "llm_playground"
    # Query access checks resolve warehouse tables and views one object at a time.
    WAREHOUSE_TABLE = "warehouse_table"
    WAREHOUSE_VIEW = "warehouse_view"


class SubjectType(StrEnum):
    """A kind of principal that can hold relations or act on a resource."""

    USER = "user"
    API_KEY = "api_key"
    SHARE_LINK = "share_link"
    EXPORT_TOKEN = "export_token"
    PROJECT_SECRET_KEY = "project_secret_key"
    SERVICE = "service"
    ROLE = "role"
