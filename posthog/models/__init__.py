# Need to skip autoimporting because this file is severely prone to circular imports errors
# You should try and make them alphabetically sorted manually if possible
# isort: skip_file

from ..batch_exports.models import BatchExport, BatchExportBackfill, BatchExportDestination, BatchExportRun

from ..session_recordings.models.session_recording import SessionRecording
from ..session_recordings.models.session_recording_playlist import SessionRecordingPlaylist
from ..session_recordings.models.session_recording_playlist_item import SessionRecordingPlaylistItem
from products.data_warehouse.backend.models import DataWarehouseTable
from ._deprecated_prompts import Prompt, PromptSequence, UserPromptState
from .action import Action
from .action.action_step import ActionStep
from .activity_logging.activity_log import ActivityLog
from .activity_logging.notification_viewed import NotificationViewed
from .alert import AlertConfiguration
from .annotation import Annotation
from .async_deletion import AsyncDeletion, DeletionType
from .async_migration import AsyncMigration, AsyncMigrationError, MigrationStatus
from .batch_imports import BatchImport
from .cohort import Cohort, CohortPeople, CohortCalculationHistory
from .column_configuration import ColumnConfiguration
from .comment import Comment
from .core_event import CoreEvent
from .data_deletion_request import DataDeletionRequest
from .data_color_theme import DataColorTheme
from ..ducklake.models import DuckgresServer, DuckLakeBackfill, DuckLakeCatalog
from .element import Element
from .element_group import ElementGroup
from .entity import Entity
from .evaluation_context import EvaluationContext, FeatureFlagEvaluationContext, TeamDefaultEvaluationContext
from .event.event import Event
from .event_buffer import EventBuffer

# TODO: remove noqa once the event filters API imports from posthog.models
from .event_filter_config import EventFilterConfig  # noqa: F401
from products.event_definitions.backend.models import EventDefinition
from products.event_definitions.backend.models import EventProperty
from .role_external_reference import RoleExternalReference
from .exported_asset import ExportedAsset
from .exported_recording import ExportedRecording
from .feature_flag import FeatureFlag
from .file_system.file_system import FileSystem
from .file_system.file_system_view_log import FileSystemViewLog
from .filters import Filter, RetentionFilter
from .group import Group
from .group_usage_metric import GroupUsageMetric
from .group_type_mapping import GroupTypeMapping
from .heatmap_saved import SavedHeatmap, HeatmapSnapshot
from .host_definition import HostDefinition
from .hog_flow import HogFlow
from .hog_functions import HogFunction
from .hog_function_template import HogFunctionTemplate
from .health_issue import HealthIssue
from .insight import Insight, InsightViewed
from .insight_caching_state import InsightCachingState
from .insight_variable import InsightVariable
from .instance_setting import InstanceSetting
from .integration import Integration
from .llm_prompt import LLMPrompt
from .materialized_column_slots import MaterializedColumnSlot, MaterializedColumnSlotState
from .messaging import MessagingRecord
from .object_media_preview import ObjectMediaPreview
from .organization import Organization, OrganizationMembership
from .organization_domain import OrganizationDomain
from .organization_integration import OrganizationIntegration
from .organization_invite import OrganizationInvite, InviteExpiredException
from .person import Person, PersonDistinctId, PersonOverride, PersonOverrideMapping
from .personal_api_key import PersonalAPIKey
from .project_secret_api_key import ProjectSecretAPIKey
from .plugin import Plugin, PluginAttachment, PluginConfig, PluginLogEntry, PluginSourceFile
from .product_intent import ProductIntent
from .project import Project
from .property import Property
from products.event_definitions.backend.models import PropertyDefinition
from .proxy_record import ProxyRecord
from .quick_filter import QuickFilter
from .remote_config import RemoteConfig
from .resource_transfer.resource_transfer import ResourceTransfer
from .scheduled_change import ScheduledChange
from products.event_definitions.backend.models import EventSchema, SchemaPropertyGroup, SchemaPropertyGroupProperty
from .share_password import SharePassword
from .sharing_configuration import SharingConfiguration
from .subscription import Subscription
from .tag import Tag
from .tagged_item import TaggedItem
from .team import Team, TeamRevenueAnalyticsConfig, TeamMarketingAnalyticsConfig
from .event_ingestion_restriction_config import EventIngestionRestrictionConfig
from .uploaded_media import UploadedMedia
from .user import User, UserManager
from .user_group import UserGroup, UserGroupMembership
from .user_integration import UserIntegration
from .repo_routing_rule import RepoRoutingRule
from .user_repo_preference import UserRepoPreference
from .user_scene_personalisation import UserScenePersonalisation
from .user_home_settings import UserHomeSettings
from .web_analytics_filter_preset import WebAnalyticsFilterPreset
from .oauth import OAuthAccessToken, OAuthApplication, OAuthGrant, OAuthIDToken, OAuthRefreshToken

from ..approvals.models import Approval, ApprovalPolicy, ChangeRequest

__all__ = [
    "Approval",
    "ApprovalPolicy",
    "ChangeRequest",
    "AlertConfiguration",
    "Action",
    "ActionStep",
    "ActivityLog",
    "Annotation",
    "AsyncDeletion",
    "AsyncMigration",
    "AsyncMigrationError",
    "BatchExport",
    "BatchExportBackfill",
    "BatchExportDestination",
    "BatchExportRun",
    "BatchImport",
    "Cohort",
    "CohortPeople",
    "CohortCalculationHistory",
    "ColumnConfiguration",
    "CoreEvent",
    "Dashboard",
    "DataDeletionRequest",
    "DashboardTile",
    "DashboardTemplate",
    "DataColorTheme",
    "DeletionType",
    "DuckgresServer",
    "DuckLakeBackfill",
    "DuckLakeCatalog",
    "Element",
    "ElementGroup",
    "Entity",
    "EvaluationContext",
    "FeatureFlagEvaluationContext",
    "TeamDefaultEvaluationContext",
    "Event",
    "EventBuffer",
    "EventDefinition",
    "EventProperty",
    "RoleExternalReference",
    "ExportedAsset",
    "ExportedRecording",
    "FeatureFlag",
    "FileSystem",
    "FileSystemViewLog",
    "Filter",
    "Group",
    "GroupUsageMetric",
    "GroupTypeMapping",
    "HeatmapSnapshot",
    "HealthIssue",
    "HogFlow",
    "HogFunction",
    "HogFunctionTemplate",
    "LLMPrompt",
    "HostDefinition",
    "Insight",
    "InsightCachingState",
    "InsightVariable",
    "InsightViewed",
    "InstanceSetting",
    "Integration",
    "InviteExpiredException",
    "MaterializedColumnSlot",
    "MaterializedColumnSlotState",
    "MessagingRecord",
    "Notebook",
    "MigrationStatus",
    "NotificationViewed",
    "ObjectMediaPreview",
    "Organization",
    "OrganizationDomain",
    "OrganizationIntegration",
    "OrganizationInvite",
    "OrganizationMembership",
    "OAuthAccessToken",
    "OAuthApplication",
    "OAuthGrant",
    "OAuthIDToken",
    "OAuthRefreshToken",
    "Person",
    "PersonDistinctId",
    "PersonalAPIKey",
    "ProjectSecretAPIKey",
    "PersonOverride",
    "PersonOverrideMapping",
    "Plugin",
    "PluginAttachment",
    "PluginConfig",
    "PluginLogEntry",
    "PluginSourceFile",
    "ProductIntent",
    "Project",
    "Property",
    "PropertyDefinition",
    "ProxyRecord",
    "QuickFilter",
    "RetentionFilter",
    "RemoteConfig",
    "ResourceTransfer",
    "EventSchema",
    "SavedHeatmap",
    "SchemaPropertyGroup",
    "SchemaPropertyGroupProperty",
    "SessionRecording",
    "SessionRecordingPlaylist",
    "SessionRecordingPlaylistItem",
    "SharePassword",
    "SharingConfiguration",
    "Subscription",
    "Tag",
    "TaggedItem",
    "Team",
    "TeamRevenueAnalyticsConfig",
    "TeamMarketingAnalyticsConfig",
    "EventIngestionRestrictionConfig",
    "UploadedMedia",
    "User",
    "RepoRoutingRule",
    "UserRepoPreference",
    "UserScenePersonalisation",
    "UserHomeSettings",
    "UserManager",
    "UserGroup",
    "UserGroupMembership",
    "UserIntegration",
    "DataWarehouseTable",
    "ScheduledChange",
    "WebAnalyticsFilterPreset",
    "Comment",
    # Deprecated models here for backwards compatibility
    "Prompt",
    "PromptSequence",
    "UserPromptState",
]
