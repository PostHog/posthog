"""DRF serializers for the customer_analytics account CRUD presentation layer.

The model-backed viewsets used to bind ``ModelSerializer``s straight to ``Account`` /
``CustomerJourney`` / ``CustomerProfileConfig``. They now serialize the facade's frozen
contracts via ``DataclassSerializer`` instead, so this module no longer imports product
models. Every field is declared explicitly to keep the generated OpenAPI components
(``Account``, ``PatchedAccount``, ``CustomerJourney``, ``CustomerProfileConfig``,
``AccountNotebook``, ``UserBasic`` …) byte-identical to the pre-isolation output.

Each serializer doubles as the viewset's ``serializer_class`` for both request and
response — drf-spectacular derives the request component (and its ``Patched`` variant)
from it exactly as it did for the ``ModelSerializer``s. The contracts carry field
defaults purely so these serializers can instantiate them from partial request bodies;
``required`` / ``read_only`` are pinned here, not by the dataclass.

``AccountOrganizationMemberSerializer`` stays a ``ModelSerializer`` — it is bound to the
core ``OrganizationMembership`` model (no customer_analytics dependency) and is imported
by the sibling ``organization_members`` module.
"""

import json
from typing import Any

from drf_spectacular.utils import extend_schema_field, extend_schema_serializer
from rest_framework import serializers
from rest_framework_dataclasses.serializers import DataclassSerializer

from posthog.api.shared import UserBasicSerializer
from posthog.models import OrganizationMembership

from products.customer_analytics.backend.facade.api import (
    AccountEmailThreadMessage,
    AccountEmailThreadSummary,
    ConversationMessageSender,
    ConversationMessageSummary,
    EmailThreadAddress,
    EmailThreadParticipantSummary,
    SupportTicketMessage,
    TicketSummary,
)
from products.customer_analytics.backend.facade.constants import (
    CUSTOM_PROPERTY_DISPLAY_TYPE_CHOICES,
    CUSTOM_PROPERTY_OPTION_COLORS,
    SLACK_SUMMARY_CADENCE_CHOICES,
)
from products.customer_analytics.backend.facade.contracts import (
    AccountAssignment,
    AccountChannelSummaryView,
    AccountNotebookView,
    AccountNoteView,
    AccountRelationship,
    AccountRelationshipDefinition,
    AccountTableField,
    AccountTrackRuleFieldKind,
    AccountTrackRulePreview,
    AccountTrackRuleRunView,
    AccountView,
    CalendarSyncStatus,
    CustomerJourneyView,
    CustomerProfileConfigView,
    CustomPropertyDefinitionView,
    CustomPropertyOption,
    CustomPropertyReference,
    CustomPropertySourceView,
    CustomPropertySyncRunView,
    EventStreamView,
    FeatureRequestAccountLinkView,
    FeatureRequestAccountView,
    FeatureRequestEvidenceView,
    FeatureRequestHistoryView,
    FeatureRequestProductAreaView,
    FeatureRequestStatusHistoryView,
    FeatureRequestView,
    MeetingParticipantView,
    MeetingView,
)


class AccountTrackRuleFieldSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=[kind.value for kind in AccountTrackRuleFieldKind])
    field = serializers.ChoiceField(
        choices=[field.value for field in AccountTableField], required=False, allow_null=True
    )
    definition_id = serializers.UUIDField(required=False, allow_null=True)

    def to_internal_value(self, data):
        return {key: value for key, value in super().to_internal_value(data).items() if value is not None}

    def to_representation(self, instance):
        return {key: value for key, value in super().to_representation(instance).items() if value is not None}


class AccountTrackRuleConditionSerializer(serializers.Serializer):
    field = AccountTrackRuleFieldSerializer()
    operator = serializers.CharField()
    values = serializers.ListField(child=serializers.JSONField(), required=False, default=list)


class AccountTrackRuleGroupSerializer(serializers.Serializer):
    conditions = AccountTrackRuleConditionSerializer(many=True)


@extend_schema_serializer(many=False)
class AccountTrackRulesConfigSerializer(serializers.Serializer):
    schema_version = serializers.IntegerField()
    version = serializers.IntegerField(min_value=0)
    enabled = serializers.BooleanField()
    groups = AccountTrackRuleGroupSerializer(many=True)


class AccountTrackRuleSampleSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(read_only=True)
    external_id = serializers.CharField(read_only=True, allow_null=True)
    rule_values = serializers.DictField(child=serializers.JSONField(), read_only=True)


class AccountTrackRulePreviewSerializer(DataclassSerializer):
    tracked_samples = AccountTrackRuleSampleSerializer(many=True, read_only=True)
    ignored_samples = AccountTrackRuleSampleSerializer(many=True, read_only=True)

    class Meta:
        dataclass = AccountTrackRulePreview
        fields = [
            "config_version",
            "eligible_active",
            "skipped_churned",
            "tracked",
            "ignored",
            "newly_ignored",
            "restored",
            "tracked_samples",
            "ignored_samples",
            "validation_errors",
        ]


class AccountTrackRuleRunSerializer(DataclassSerializer):
    id = serializers.UUIDField(read_only=True)
    config_version = serializers.IntegerField(read_only=True, min_value=0)
    trigger = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    eligible_active = serializers.IntegerField(read_only=True, min_value=0)
    skipped_churned = serializers.IntegerField(read_only=True, min_value=0)
    tracked = serializers.IntegerField(read_only=True, min_value=0)
    ignored = serializers.IntegerField(read_only=True, min_value=0)
    newly_ignored = serializers.IntegerField(read_only=True, min_value=0)
    restored = serializers.IntegerField(read_only=True, min_value=0)
    started_at = serializers.DateTimeField(read_only=True, allow_null=True)
    finished_at = serializers.DateTimeField(read_only=True, allow_null=True)
    error = serializers.CharField(read_only=True, allow_null=True)
    created_by = serializers.IntegerField(read_only=True, allow_null=True)
    created_at = serializers.DateTimeField(read_only=True)

    class Meta:
        dataclass = AccountTrackRuleRunView
        fields = [
            "id",
            "config_version",
            "trigger",
            "status",
            "eligible_active",
            "skipped_churned",
            "tracked",
            "ignored",
            "newly_ignored",
            "restored",
            "started_at",
            "finished_at",
            "error",
            "created_by",
            "created_at",
        ]


class AccountTrackRuleRunRequestSerializer(serializers.Serializer):
    idempotency_key = serializers.UUIDField()
    confirmed = serializers.BooleanField()

    def validate_confirmed(self, value: bool) -> bool:
        if not value:
            raise serializers.ValidationError("Confirm before running Track Rules.")
        return value


# Scope (value, label) pairs, kept in sync with ``CustomerProfileConfig.Scope``. Declared
# here rather than read off the model so this module imports no product models — the
# generated ``CustomerProfileConfigScopeEnum`` stays identical to the model-derived one.
_PROFILE_CONFIG_SCOPE_CHOICES = [
    ("person", "Person"),
    ("group_0", "Group 0"),
    ("group_1", "Group 1"),
    ("group_2", "Group 2"),
    ("group_3", "Group 3"),
    ("group_4", "Group 4"),
]

_ACCOUNT_PROPERTIES_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "website_domain": {
            "type": "string",
            "nullable": True,
            "description": "Primary company website hostname used for account identity and logo lookup.",
        },
        "email_domains": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Email domains owned by this account's company, used to match inbound touchpoints to the account.",
        },
        "known_emails": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Individual email addresses pinned to this account, matched before the domain fallback.",
        },
        "stripe_customer_id": {"type": "string", "nullable": True},
        "hubspot_deal_id": {"type": "string", "nullable": True},
        "billing_id": {"type": "string", "nullable": True},
        "sfdc_id": {"type": "string", "nullable": True},
        "zendesk_id": {"type": "string", "nullable": True},
        "slack_channel_id": {"type": "string", "nullable": True},
        "usage_dashboard_link": {"type": "string", "nullable": True},
        "metabase_link": {"type": "string", "nullable": True},
    },
}


@extend_schema_field(_ACCOUNT_PROPERTIES_SCHEMA)
class AccountPropertiesField(serializers.JSONField):
    pass


_FEATURE_REQUEST_STATUS_CHOICES = [
    ("requested", "Requested"),
    ("planned", "Planned"),
    ("completed", "Completed"),
    ("wont_fix", "Won't fix"),
    ("duplicate", "Duplicate"),
]
_FEATURE_REQUEST_PRIORITY_CHOICES = [("high", "High"), ("medium", "Medium"), ("low", "Low")]
_FEATURE_REQUEST_PRIORITY_FILTER_CHOICES = [*_FEATURE_REQUEST_PRIORITY_CHOICES, ("none", "No priority")]
_FEATURE_REQUEST_ARCHIVE_CHOICES = [("active", "Active"), ("archived", "Archived"), ("all", "All")]
_FEATURE_REQUEST_ORDERING_CHOICES = [
    ("-updated_at", "Last updated: newest"),
    ("updated_at", "Last updated: oldest"),
    ("-created_at", "Date created: newest"),
    ("created_at", "Date created: oldest"),
    ("-priority", "Priority: high to low"),
    ("priority", "Priority: low to high"),
    ("title", "Title: A to Z"),
    ("-title", "Title: Z to A"),
    ("account", "Accounts: A to Z"),
    ("-account", "Accounts: Z to A"),
    ("product_area", "Product areas: A to Z"),
    ("-product_area", "Product areas: Z to A"),
    ("status", "Status: A to Z"),
    ("-status", "Status: Z to A"),
    ("created_by", "Created by: A to Z"),
    ("-created_by", "Created by: Z to A"),
    ("evidence_count", "Evidence: low to high"),
    ("-evidence_count", "Evidence: high to low"),
]


class FeatureRequestProductAreaSerializer(DataclassSerializer):
    id = serializers.UUIDField(read_only=True, help_text="Stable product area ID.")
    name = serializers.CharField(max_length=200, help_text="Team-maintained product area name.")
    display_order = serializers.IntegerField(
        required=False,
        min_value=0,
        default=0,
        help_text="Position in product area selectors. Lower values appear first.",
    )
    is_active = serializers.BooleanField(
        required=False,
        default=True,
        help_text="Whether editors can select this product area for new requests.",
    )
    created_at = serializers.DateTimeField(read_only=True, help_text="When the product area was created.")
    updated_at = serializers.DateTimeField(read_only=True, help_text="When the product area was last updated.")

    class Meta:
        dataclass = FeatureRequestProductAreaView
        ref_name = "FeatureRequestProductArea"
        fields = ["id", "name", "display_order", "is_active", "created_at", "updated_at"]


class FeatureRequestProductAreaListQuerySerializer(serializers.Serializer):
    include_inactive = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Include inactive product areas. Defaults to false.",
    )


class FeatureRequestAccountSerializer(DataclassSerializer):
    id = serializers.UUIDField(read_only=True, help_text="ID of the affected Customer Analytics account.")
    name = serializers.CharField(read_only=True, help_text="Name of the affected account.")

    class Meta:
        dataclass = FeatureRequestAccountView
        ref_name = "FeatureRequestAccount"
        fields = ["id", "name"]


class FeatureRequestEvidenceSerializer(DataclassSerializer):
    id = serializers.UUIDField(read_only=True, help_text="Stable evidence ID.")
    summary = serializers.CharField(read_only=True, help_text="Internal summary of this account's request evidence.")
    customer_quote = serializers.CharField(read_only=True, help_text="Customer quote kept with this evidence item.")
    evidence_source = serializers.CharField(
        read_only=True,
        max_length=200,
        help_text="Free-form name of the source where this evidence was recorded.",
    )
    source_url = serializers.URLField(read_only=True, help_text="HTTP or HTTPS link to the source, or an empty string.")
    requested_on = serializers.DateField(
        read_only=True,
        allow_null=True,
        help_text="Date the account made the request, or null when unknown.",
    )
    image_ids = serializers.ListField(
        child=serializers.UUIDField(),
        read_only=True,
        help_text="Uploaded image IDs attached to this evidence item, in display order.",
    )
    created_by = serializers.IntegerField(
        read_only=True, allow_null=True, help_text="ID of the user who added the evidence."
    )
    updated_by = serializers.IntegerField(
        read_only=True, allow_null=True, help_text="ID of the last user to update the evidence."
    )
    created_at = serializers.DateTimeField(read_only=True, help_text="When the evidence was added.")
    updated_at = serializers.DateTimeField(read_only=True, help_text="When the evidence was last updated.")

    class Meta:
        dataclass = FeatureRequestEvidenceView
        ref_name = "FeatureRequestEvidence"
        fields = [
            "id",
            "summary",
            "customer_quote",
            "evidence_source",
            "source_url",
            "requested_on",
            "image_ids",
            "created_by",
            "updated_by",
            "created_at",
            "updated_at",
        ]


class FeatureRequestAccountLinkSerializer(DataclassSerializer):
    id = serializers.UUIDField(read_only=True, help_text="Stable link ID between the request and account.")
    account = FeatureRequestAccountSerializer(read_only=True, help_text="Affected Customer Analytics account.")
    evidence = FeatureRequestEvidenceSerializer(
        many=True,
        read_only=True,
        help_text="Evidence recorded for this account and request. List responses omit these items.",
    )
    evidence_count = serializers.IntegerField(
        read_only=True,
        min_value=0,
        help_text="Total evidence items recorded for this account and request.",
    )
    created_at = serializers.DateTimeField(read_only=True, help_text="When the account was first linked.")
    updated_at = serializers.DateTimeField(
        read_only=True,
        allow_null=True,
        help_text="When the account link was last changed.",
    )

    class Meta:
        dataclass = FeatureRequestAccountLinkView
        ref_name = "FeatureRequestAccountLink"
        fields = ["id", "account", "evidence", "evidence_count", "created_at", "updated_at"]


class FeatureRequestSerializer(DataclassSerializer):
    id = serializers.UUIDField(read_only=True, help_text="Stable feature request ID.")
    title = serializers.CharField(read_only=True, help_text="Customer-facing request title.")
    description = serializers.CharField(read_only=True, help_text="Customer-facing request description in Markdown.")
    request_status = serializers.ChoiceField(
        read_only=True,
        choices=_FEATURE_REQUEST_STATUS_CHOICES,
        help_text="Current customer-facing lifecycle status.",
    )
    request_priority = serializers.ChoiceField(
        read_only=True,
        allow_null=True,
        choices=_FEATURE_REQUEST_PRIORITY_CHOICES,
        help_text="Manual request priority. Null means no priority.",
    )
    is_archived = serializers.BooleanField(read_only=True, help_text="Whether the request is archived.")
    archived_at = serializers.DateTimeField(
        read_only=True,
        allow_null=True,
        help_text="When the request was archived, or null while active.",
    )
    archived_by = serializers.IntegerField(
        read_only=True,
        allow_null=True,
        help_text="ID of the user who archived the request, or null while active.",
    )
    version = serializers.IntegerField(
        read_only=True,
        min_value=1,
        help_text="Version required for optimistic concurrency on mutations.",
    )
    can_update = serializers.BooleanField(
        read_only=True,
        help_text="Whether the caller can update this request and all its active account links.",
    )
    account = FeatureRequestAccountSerializer(
        read_only=True,
        help_text="First visible account retained for client compatibility. Use account_links for the complete list.",
    )
    account_links = FeatureRequestAccountLinkSerializer(
        many=True,
        read_only=True,
        help_text="Active account links visible to the caller, with account-specific evidence.",
    )
    evidence_count = serializers.IntegerField(
        read_only=True,
        min_value=0,
        help_text="Total evidence items recorded across visible account links.",
    )
    product_areas = FeatureRequestProductAreaSerializer(
        many=True,
        read_only=True,
        help_text="Product areas affected by this request.",
    )
    created_by = serializers.IntegerField(
        read_only=True, allow_null=True, help_text="ID of the user who created the request."
    )
    updated_by = serializers.IntegerField(
        read_only=True, allow_null=True, help_text="ID of the last user to update the request."
    )
    created_at = serializers.DateTimeField(read_only=True, help_text="When the request was created.")
    updated_at = serializers.DateTimeField(read_only=True, help_text="When the request was last updated.")

    class Meta:
        dataclass = FeatureRequestView
        ref_name = "FeatureRequest"
        fields = [
            "id",
            "title",
            "description",
            "request_status",
            "request_priority",
            "is_archived",
            "archived_at",
            "archived_by",
            "version",
            "can_update",
            "account",
            "account_links",
            "evidence_count",
            "product_areas",
            "created_by",
            "updated_by",
            "created_at",
            "updated_at",
        ]


_FEATURE_REQUEST_HISTORY_VALUE_SCHEMA = {
    "nullable": True,
    "oneOf": [
        {"type": "string"},
        {
            "type": "object",
            "required": ["id", "name"],
            "properties": {
                "id": {"type": "string", "format": "uuid", "nullable": True},
                "name": {"type": "string"},
            },
        },
        {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "name"],
                "properties": {
                    "id": {"type": "string", "format": "uuid"},
                    "name": {"type": "string"},
                },
            },
        },
        {
            "type": "object",
            "required": [
                "id",
                "account",
                "summary",
                "customer_quote",
                "source",
                "source_url",
                "requested_on",
            ],
            "properties": {
                "id": {"type": "string", "format": "uuid"},
                "account": {
                    "type": "object",
                    "required": ["id", "name"],
                    "properties": {
                        "id": {"type": "string", "format": "uuid"},
                        "name": {"type": "string"},
                    },
                },
                "summary": {"type": "string"},
                "customer_quote": {"type": "string"},
                "source": {"type": "string"},
                "source_url": {"type": "string"},
                "requested_on": {"type": "string", "format": "date", "nullable": True},
                "image_ids": {
                    "type": "array",
                    "items": {"type": "string", "format": "uuid"},
                },
            },
        },
    ],
}


@extend_schema_field(_FEATURE_REQUEST_HISTORY_VALUE_SCHEMA)
class FeatureRequestHistoryValueField(serializers.JSONField):
    pass


class FeatureRequestHistoryChangeSerializer(serializers.Serializer):
    field = serializers.ChoiceField(
        read_only=True,
        choices=[
            ("status", "Status"),
            ("priority", "Priority"),
            ("account", "Account"),
            ("accounts", "Accounts"),
            ("evidence", "Evidence"),
            ("product_areas", "Product areas"),
        ],
        help_text="Request field represented by this change.",
    )
    before = FeatureRequestHistoryValueField(
        read_only=True,
        help_text="Value before the update, including relation snapshots.",
    )
    after = FeatureRequestHistoryValueField(
        read_only=True,
        help_text="Value after the update, including relation snapshots.",
    )


class FeatureRequestHistorySerializer(DataclassSerializer):
    id = serializers.UUIDField(read_only=True, help_text="Stable request history entry ID.")
    changes = FeatureRequestHistoryChangeSerializer(
        many=True,
        read_only=True,
        help_text="Tracked fields changed together in one successful save.",
    )
    is_initial = serializers.BooleanField(
        read_only=True,
        help_text="Whether this entry records the request's initial values.",
    )
    change_source = serializers.ChoiceField(
        read_only=True,
        choices=[("manual", "Manual")],
        help_text="System that recorded the request change.",
    )
    actor_id = serializers.IntegerField(
        read_only=True,
        allow_null=True,
        help_text="ID of the user who changed the request, if known.",
    )
    actor_name = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text="Display name of the user who changed the request, if known.",
    )
    changed_at = serializers.DateTimeField(read_only=True, help_text="When the request changed.")

    class Meta:
        dataclass = FeatureRequestHistoryView
        ref_name = "FeatureRequestHistory"
        fields = [
            "id",
            "changes",
            "is_initial",
            "change_source",
            "actor_id",
            "actor_name",
            "changed_at",
        ]


class FeatureRequestStatusHistorySerializer(DataclassSerializer):
    id = serializers.UUIDField(read_only=True, help_text="Stable status history entry ID.")
    previous_status = serializers.ChoiceField(
        read_only=True,
        allow_null=True,
        choices=_FEATURE_REQUEST_STATUS_CHOICES,
        help_text="Status before this change. Null identifies the initial status.",
    )
    request_status = serializers.ChoiceField(
        read_only=True,
        choices=_FEATURE_REQUEST_STATUS_CHOICES,
        help_text="Status after this change.",
    )
    change_source = serializers.ChoiceField(
        read_only=True,
        choices=[("manual", "Manual")],
        help_text="System that recorded the status change.",
    )
    actor_id = serializers.IntegerField(
        read_only=True,
        allow_null=True,
        help_text="ID of the user who changed the status, if known.",
    )
    actor_name = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text="Display name of the user who changed the status, if known.",
    )
    changed_at = serializers.DateTimeField(read_only=True, help_text="When the status changed.")

    class Meta:
        dataclass = FeatureRequestStatusHistoryView
        ref_name = "FeatureRequestStatusHistory"
        fields = [
            "id",
            "previous_status",
            "request_status",
            "change_source",
            "actor_id",
            "actor_name",
            "changed_at",
        ]


class CommaSeparatedListField(serializers.ListField):
    def to_internal_value(self, data: Any) -> list[Any]:
        if isinstance(data, str):
            data = data.split(",")
        elif isinstance(data, list):
            data = [item for value in data for item in (value.split(",") if isinstance(value, str) else [value])]
        return super().to_internal_value(data)


class FeatureRequestListQuerySerializer(serializers.Serializer):
    search = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Case-insensitive text to find in request titles and descriptions.",
    )
    statuses = CommaSeparatedListField(
        required=False,
        child=serializers.ChoiceField(choices=_FEATURE_REQUEST_STATUS_CHOICES),
        help_text="Lifecycle statuses to include. Multiple values use OR semantics.",
    )
    priorities = CommaSeparatedListField(
        required=False,
        child=serializers.ChoiceField(choices=_FEATURE_REQUEST_PRIORITY_FILTER_CHOICES),
        help_text="Priorities to include. Use none for requests without a priority.",
    )
    product_area_ids = CommaSeparatedListField(
        required=False,
        child=serializers.UUIDField(),
        help_text="Product area IDs to include. Multiple values use OR semantics.",
    )
    account_ids = CommaSeparatedListField(
        required=False,
        child=serializers.UUIDField(),
        help_text="Accessible account IDs to include. Multiple values use OR semantics.",
    )
    created_by_ids = CommaSeparatedListField(
        required=False,
        child=serializers.IntegerField(min_value=1),
        help_text="Creator user IDs to include. Multiple values use OR semantics.",
    )
    archive_state = serializers.ChoiceField(
        required=False,
        default="active",
        choices=_FEATURE_REQUEST_ARCHIVE_CHOICES,
        help_text="Whether to return active requests, archived requests, or all requests.",
    )
    request_ordering = serializers.ChoiceField(
        required=False,
        default="-updated_at",
        choices=_FEATURE_REQUEST_ORDERING_CHOICES,
        help_text="Stable ordering for the result list.",
    )


class FeatureRequestEvidencePayloadSerializer(serializers.Serializer):
    summary = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        trim_whitespace=True,
        help_text="Internal summary of this account's request evidence.",
    )
    customer_quote = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        trim_whitespace=True,
        help_text="Customer quote kept with this evidence item.",
    )
    evidence_source = serializers.CharField(
        max_length=200,
        help_text="Free-form name of the source where this evidence was recorded.",
    )
    source_url = serializers.URLField(
        required=False,
        allow_blank=True,
        default="",
        max_length=2000,
        help_text="Optional HTTP or HTTPS link to the source.",
    )
    requested_on = serializers.DateField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Date the account made the request, or null when unknown.",
    )
    image_ids = serializers.ListField(
        required=False,
        child=serializers.UUIDField(),
        help_text="Uploaded image IDs from this project to attach in display order.",
    )


class FeatureRequestCreateSerializer(serializers.Serializer):
    title = serializers.CharField(
        max_length=400,
        trim_whitespace=True,
        help_text="Required customer-facing request title.",
    )
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        trim_whitespace=True,
        help_text="Optional customer-facing request description in Markdown.",
    )
    account_id = serializers.UUIDField(help_text="ID of the affected Customer Analytics account.")
    product_area_ids = serializers.ListField(
        child=serializers.UUIDField(),
        allow_empty=False,
        help_text="One or more active product area IDs. Duplicate IDs are ignored.",
    )
    idempotency_key = serializers.UUIDField(
        help_text="Client-generated key that makes retries return the original request instead of creating a duplicate.",
    )
    evidence = FeatureRequestEvidencePayloadSerializer(
        required=False,
        allow_null=True,
        help_text="Optional first evidence item to create for the selected account.",
    )


class FeatureRequestUpdateSerializer(serializers.Serializer):
    expected_version = serializers.IntegerField(
        min_value=1,
        help_text="Request version loaded by the editor. Stale versions return 409 Conflict.",
    )
    title = serializers.CharField(
        required=False,
        max_length=400,
        trim_whitespace=True,
        help_text="Updated customer-facing request title.",
    )
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        trim_whitespace=True,
        help_text="Updated optional customer-facing request description in Markdown.",
    )
    account_id = serializers.UUIDField(
        required=False,
        help_text="Deprecated single affected account ID. Use account_ids.",
    )
    account_ids = serializers.ListField(
        required=False,
        child=serializers.UUIDField(),
        allow_empty=False,
        help_text="One or more affected account IDs. Removed accounts are unlinked without deleting their evidence.",
    )
    product_area_ids = serializers.ListField(
        required=False,
        child=serializers.UUIDField(),
        allow_empty=False,
        help_text="One or more product area IDs. Existing inactive areas can remain linked.",
    )
    request_status = serializers.ChoiceField(
        required=False,
        choices=_FEATURE_REQUEST_STATUS_CHOICES,
        help_text="Updated customer-facing lifecycle status.",
    )
    request_priority = serializers.ChoiceField(
        required=False,
        allow_null=True,
        choices=_FEATURE_REQUEST_PRIORITY_CHOICES,
        help_text="Updated manual priority. Pass null to remove the priority.",
    )


class FeatureRequestEvidenceWriteSerializer(FeatureRequestEvidencePayloadSerializer):
    expected_version = serializers.IntegerField(
        min_value=1,
        help_text="Request version loaded by the editor. Stale versions return 409 Conflict.",
    )


class FeatureRequestAddAccountSerializer(serializers.Serializer):
    expected_version = serializers.IntegerField(
        min_value=1,
        help_text="Request version loaded by the editor. Stale versions return 409 Conflict.",
    )
    account_id = serializers.UUIDField(help_text="Accessible account to link to this feature request.")
    evidence = FeatureRequestEvidencePayloadSerializer(
        required=False,
        allow_null=True,
        help_text="Optional first evidence item to create for the account in the same change.",
    )


class FeatureRequestEvidenceCreateSerializer(FeatureRequestEvidenceWriteSerializer):
    account_link_id = serializers.UUIDField(help_text="Active account link that owns this evidence.")


class FeatureRequestEvidenceUpdateSerializer(FeatureRequestEvidenceWriteSerializer):
    evidence_id = serializers.UUIDField(help_text="Evidence item to replace.")


class FeatureRequestEvidenceDeleteSerializer(serializers.Serializer):
    expected_version = serializers.IntegerField(
        min_value=1,
        help_text="Request version loaded by the editor. Stale versions return 409 Conflict.",
    )
    evidence_id = serializers.UUIDField(help_text="Evidence item to delete.")


class FeatureRequestVersionSerializer(serializers.Serializer):
    expected_version = serializers.IntegerField(
        min_value=1,
        help_text="Request version loaded by the editor. Stale versions return 409 Conflict.",
    )


class CustomerProfileConfigSerializer(DataclassSerializer):
    id = serializers.UUIDField(read_only=True)
    scope = serializers.ChoiceField(choices=_PROFILE_CONFIG_SCOPE_CHOICES)
    content = serializers.JSONField(required=False, allow_null=True, default=dict)
    sidebar = serializers.JSONField(required=False, allow_null=True, default=dict)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True, allow_null=True)

    class Meta:
        dataclass = CustomerProfileConfigView
        # Pin the OpenAPI component name to the pre-isolation one (DataclassSerializer would
        # otherwise name it after the wrapped dataclass, ``CustomerProfileConfigView``).
        ref_name = "CustomerProfileConfig"
        fields = ["id", "scope", "content", "sidebar", "created_at", "updated_at"]

    def validate_content(self, value):
        return self._validate_json(field="content", value=value)

    def validate_sidebar(self, value):
        return self._validate_json(field="sidebar", value=value)

    def _validate_json(self, field: str, value):
        self.fields[field].run_validation(value)

        if value is None:
            return {}

        if not isinstance(value, dict | list):
            raise serializers.ValidationError(f"Invalid value for field '{field}'")

        try:
            json.dumps(value)
        except (ValueError, TypeError):
            raise serializers.ValidationError(f"Invalid value for field '{field}'")

        return value


class CustomerJourneySerializer(DataclassSerializer):
    id = serializers.UUIDField(read_only=True)
    insight = serializers.IntegerField()
    name = serializers.CharField(max_length=400)
    description = serializers.CharField(required=False, allow_null=True)
    created_at = serializers.DateTimeField(read_only=True)
    created_by = serializers.IntegerField(read_only=True, allow_null=True)
    updated_at = serializers.DateTimeField(read_only=True, allow_null=True)

    class Meta:
        dataclass = CustomerJourneyView
        ref_name = "CustomerJourney"
        fields = ["id", "insight", "name", "description", "created_at", "created_by", "updated_at"]


class AccountSerializer(DataclassSerializer):
    """A Customer Analytics account — a logical grouping used to assign customer-success ownership."""

    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(
        max_length=400,
        help_text="Human-readable name of the account.",
    )
    external_id = serializers.CharField(
        max_length=400,
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text=(
            "Identifier linking this account to its source customer — the analytics group key "
            "(the customer's organization id), used to match billing and external records. Optional."
        ),
    )
    properties = AccountPropertiesField(
        required=False,
        allow_null=True,
        help_text=(
            "Typed account properties: website_domain, external system identifiers (stripe_customer_id, "
            "hubspot_deal_id, billing_id, sfdc_id, zendesk_id, slack_channel_id, "
            "usage_dashboard_link, metabase_link), and touchpoint matching lists: email_domains "
            "(the company's email domains) and known_emails (individual addresses pinned to the "
            "account). Defaults to an empty object. Unknown keys are rejected. User assignments "
            "live on account relationships, not here."
        ),
    )
    tags = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Tag names attached to the account. Pass a list to replace existing tags.",
    )
    notebooks = serializers.ListField(
        child=serializers.CharField(),
        read_only=True,
        help_text=(
            "Short IDs of the internal notebooks linked to this account, used to persist investigations, "
            "call notes, and other free-form context. Empty list if no notebooks have been created for the account."
        ),
    )
    slack_summary_cadence = serializers.ChoiceField(
        choices=SLACK_SUMMARY_CADENCE_CHOICES,
        required=False,
        allow_null=True,
        help_text=(
            "How often to generate an AI summary of the account's bound Slack channel "
            "(daily, weekly, or monthly). Null means summaries are off."
        ),
    )
    churned_at = serializers.DateTimeField(
        required=False,
        allow_null=True,
        help_text="When the account churned. Null means the account has not churned.",
    )
    ignored_at = serializers.DateTimeField(
        read_only=True,
        allow_null=True,
        help_text="When Track Rules ignored the account. Null means the account is tracked.",
    )
    created_at = serializers.DateTimeField(read_only=True)
    created_by = serializers.IntegerField(read_only=True, allow_null=True)
    updated_at = serializers.DateTimeField(read_only=True, allow_null=True)

    class Meta:
        dataclass = AccountView
        ref_name = "Account"
        fields = [
            "id",
            "name",
            "external_id",
            "properties",
            "tags",
            "notebooks",
            "slack_summary_cadence",
            "churned_at",
            "ignored_at",
            "created_at",
            "created_by",
            "updated_at",
        ]

    def validate_properties(self, value):
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise serializers.ValidationError("properties must be a JSON object.")
        try:
            json.dumps(value)
        except (TypeError, ValueError):
            raise serializers.ValidationError("properties must be JSON-serializable.")
        return value


class AccountOrganizationMemberSerializer(serializers.ModelSerializer):
    """Slim organization-member representation for Customer analytics account rows."""

    user = UserBasicSerializer(
        read_only=True,
        help_text="Basic profile of the member's user (uuid, distinct_id, first_name, last_name, email).",
    )

    class Meta:
        model = OrganizationMembership
        fields = ["id", "user", "level"]
        read_only_fields = ["id", "user", "level"]
        extra_kwargs = {
            "id": {"help_text": "Organization membership ID."},
            "level": {"help_text": "Organization access level: member, admin, or owner."},
        }


class AccountNotebookSerializer(DataclassSerializer):
    id = serializers.UUIDField(read_only=True)
    short_id = serializers.CharField(read_only=True)
    created_by = UserBasicSerializer(read_only=True)
    last_modified_by = UserBasicSerializer(read_only=True)
    title = serializers.CharField(
        max_length=256,
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Human-readable title of the account notebook.",
    )
    content = serializers.JSONField(
        required=False,
        allow_null=True,
        help_text="Notebook content as a ProseMirror JSON document structure.",
    )
    text_content = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Plain text representation of the notebook content for search.",
    )
    created_at = serializers.DateTimeField(read_only=True)
    last_modified_at = serializers.DateTimeField(read_only=True)

    class Meta:
        dataclass = AccountNotebookView
        ref_name = "AccountNotebook"
        fields = [
            "id",
            "short_id",
            "title",
            "content",
            "text_content",
            "created_at",
            "created_by",
            "last_modified_at",
            "last_modified_by",
        ]


class AccountNoteSerializer(DataclassSerializer):
    """A team-wide account note — an internal notebook linked to a Customer analytics account."""

    short_id = serializers.CharField(read_only=True, help_text="URL-safe short ID of the notebook.")
    title = serializers.CharField(read_only=True, allow_null=True, help_text="Title of the note.")
    created_at = serializers.DateTimeField(read_only=True, help_text="When the note was created.")
    last_modified_at = serializers.DateTimeField(read_only=True, help_text="When the note was last modified.")
    account_id = serializers.UUIDField(read_only=True, help_text="UUID of the account this note is linked to.")
    account_name = serializers.CharField(read_only=True, help_text="Name of the account this note is linked to.")
    created_by = UserBasicSerializer(read_only=True, allow_null=True, help_text="User who created the note, if known.")

    class Meta:
        dataclass = AccountNoteView
        ref_name = "AccountNote"
        fields = ["short_id", "title", "created_at", "last_modified_at", "account_id", "account_name", "created_by"]


class ChannelSummaryMessageSerializer(serializers.Serializer):
    """Metadata for one message a channel summary covered — never the message text."""

    author = serializers.CharField(read_only=True, help_text="Display name of the message author.")
    sent_at = serializers.DateTimeField(read_only=True, help_text="When the message was sent.")
    permalink = serializers.CharField(read_only=True, help_text="Slack permalink to the message.")


class AccountChannelSummarySerializer(DataclassSerializer):
    """An AI summary of one closed period of the account's bound Slack channel (read-only)."""

    id = serializers.UUIDField(read_only=True, help_text="UUID of the summary.")
    slack_channel_id = serializers.CharField(
        read_only=True, help_text="Slack channel the summary covered — kept even if the account is later rebound."
    )
    cadence = serializers.ChoiceField(
        read_only=True,
        choices=SLACK_SUMMARY_CADENCE_CHOICES,
        help_text="Cadence the summarized period belongs to (daily, weekly, or monthly).",
    )
    period_start = serializers.DateTimeField(read_only=True, help_text="Start of the summarized period (inclusive).")
    period_end = serializers.DateTimeField(read_only=True, help_text="End of the summarized period (exclusive).")
    content = serializers.CharField(
        read_only=True, help_text="Markdown summary citing the original Slack messages with permalinks."
    )
    message_count = serializers.IntegerField(
        read_only=True, help_text="Number of channel messages the summary covered."
    )
    messages = ChannelSummaryMessageSerializer(
        many=True,
        read_only=True,
        help_text="The messages the summary covered, in transcript order — metadata only, no message text.",
    )
    generated_at = serializers.DateTimeField(read_only=True, help_text="When the summary was generated.")

    class Meta:
        dataclass = AccountChannelSummaryView
        ref_name = "AccountChannelSummary"
        fields = [
            "id",
            "slack_channel_id",
            "cadence",
            "period_start",
            "period_end",
            "content",
            "message_count",
            "messages",
            "generated_at",
        ]


class ConversationMessageSenderSerializer(DataclassSerializer):
    name = serializers.CharField(read_only=True, help_text="Display name of the message sender.")
    email = serializers.EmailField(
        read_only=True,
        allow_null=True,
        help_text="Email address of the message sender, when available.",
    )
    person_id = serializers.UUIDField(
        read_only=True,
        allow_null=True,
        help_text="UUID of the matched PostHog person, when available.",
    )
    distinct_id = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text="Distinct ID of the sender, when available.",
    )

    class Meta:
        dataclass = ConversationMessageSender
        ref_name = "ConversationMessageSender"
        fields = ["name", "email", "person_id", "distinct_id"]


class ConversationMessageSummarySerializer(DataclassSerializer):
    sender = ConversationMessageSenderSerializer(read_only=True, help_text="Sender of the message.")
    sent_at = serializers.DateTimeField(read_only=True, help_text="Timestamp from the message source.")
    direction = serializers.ChoiceField(
        read_only=True,
        choices=[("inbound", "Inbound"), ("outbound", "Outbound")],
        help_text="Whether PostHog received or sent the message.",
    )

    class Meta:
        dataclass = ConversationMessageSummary
        ref_name = "ConversationMessageSummary"
        fields = ["sender", "sent_at", "direction"]


class SupportTicketMessageSerializer(DataclassSerializer):
    id = serializers.UUIDField(read_only=True, help_text="UUID of the support ticket message.")
    content = serializers.CharField(read_only=True, allow_blank=True, help_text="Plain-text message content.")
    author_name = serializers.CharField(read_only=True, help_text="Display name of the message author.")
    direction = serializers.ChoiceField(
        read_only=True,
        choices=[("inbound", "Inbound"), ("outbound", "Outbound")],
        help_text="Whether PostHog received or sent the message.",
    )
    is_private = serializers.BooleanField(
        read_only=True,
        help_text="Whether the message is an internal note hidden from the customer.",
    )
    created_at = serializers.DateTimeField(read_only=True, help_text="When the message was created.")

    class Meta:
        dataclass = SupportTicketMessage
        ref_name = "AccountSupportTicketMessage"
        fields = ["id", "content", "author_name", "direction", "is_private", "created_at"]


class SupportTicketSerializer(DataclassSerializer):
    """A support ticket linked to an account, sourced from the conversations product (read-only)."""

    id = serializers.CharField(read_only=True, help_text="UUID of the support ticket.")
    ticket_number = serializers.IntegerField(read_only=True, help_text="Human-readable ticket number.")
    status = serializers.CharField(read_only=True, help_text="Current status of the ticket (e.g. 'new', 'open').")
    last_message_at = serializers.DateTimeField(
        read_only=True, allow_null=True, help_text="When the most recent message was sent on this ticket."
    )
    last_message_text = serializers.CharField(
        read_only=True, allow_null=True, help_text="Truncated preview of the most recent message."
    )
    last_message = ConversationMessageSummarySerializer(
        read_only=True,
        allow_null=True,
        help_text="Sender, timestamp, and direction of the latest public message, when available.",
    )
    deep_link = serializers.CharField(read_only=True, help_text="Absolute URL to open this ticket in the app.")
    created_at = serializers.DateTimeField(read_only=True, help_text="When the ticket conversation started.")
    started_by = serializers.CharField(read_only=True, help_text="Display name of the customer who started the ticket.")
    distinct_id = serializers.CharField(read_only=True, help_text="Distinct ID of the customer who started the ticket.")

    class Meta:
        dataclass = TicketSummary
        ref_name = "SupportTicket"
        fields = [
            "id",
            "ticket_number",
            "status",
            "last_message_at",
            "last_message_text",
            "last_message",
            "deep_link",
            "created_at",
            "started_by",
            "distinct_id",
        ]


class EmailThreadParticipantSerializer(DataclassSerializer):
    email = serializers.EmailField(read_only=True, help_text="Email address of the thread participant.")
    display_name = serializers.CharField(
        read_only=True,
        allow_blank=True,
        help_text="Display name from the captured email headers.",
    )
    kind = serializers.ChoiceField(
        read_only=True,
        choices=[("internal", "Internal"), ("customer", "Customer")],
        help_text="Whether the participant belongs to the PostHog organization or the customer.",
    )
    person_id = serializers.UUIDField(
        read_only=True,
        allow_null=True,
        help_text="UUID of the matched PostHog person for a customer participant, when available.",
    )

    class Meta:
        dataclass = EmailThreadParticipantSummary
        ref_name = "AccountEmailThreadParticipant"
        fields = ["email", "display_name", "kind", "person_id"]


class AccountEmailThreadSerializer(DataclassSerializer):
    id = serializers.UUIDField(read_only=True, help_text="UUID of the captured email thread.")
    subject = serializers.CharField(read_only=True, allow_blank=True, help_text="Email thread subject.")
    preview = serializers.CharField(
        read_only=True,
        allow_blank=True,
        help_text="Plain-text preview of the latest captured message.",
    )
    first_message_at = serializers.DateTimeField(
        read_only=True,
        allow_null=True,
        help_text="Source timestamp of the first captured message.",
    )
    first_message = ConversationMessageSummarySerializer(
        read_only=True,
        allow_null=True,
        help_text="Sender, timestamp, and direction of the first captured message, when available.",
    )
    last_message_at = serializers.DateTimeField(
        read_only=True,
        allow_null=True,
        help_text="Source timestamp of the latest captured message.",
    )
    last_message = ConversationMessageSummarySerializer(
        read_only=True,
        allow_null=True,
        help_text="Sender, timestamp, and direction of the latest captured message, when available.",
    )
    message_count = serializers.IntegerField(
        read_only=True,
        help_text="Number of captured messages in the thread.",
    )
    participants = EmailThreadParticipantSerializer(
        many=True,
        read_only=True,
        help_text="Participants included in the email thread.",
    )

    class Meta:
        dataclass = AccountEmailThreadSummary
        ref_name = "AccountEmailThread"
        fields = [
            "id",
            "subject",
            "preview",
            "first_message_at",
            "first_message",
            "last_message_at",
            "last_message",
            "message_count",
            "participants",
        ]


class EmailThreadAddressSerializer(DataclassSerializer):
    name = serializers.CharField(read_only=True, allow_blank=True, help_text="Name from the email header.")
    email = serializers.EmailField(read_only=True, help_text="Email address from the email header.")

    class Meta:
        dataclass = EmailThreadAddress
        ref_name = "AccountEmailThreadAddress"
        fields = ["name", "email"]


class AccountEmailThreadMessageSerializer(DataclassSerializer):
    id = serializers.UUIDField(read_only=True, help_text="UUID of the captured email message.")
    sent_at = serializers.DateTimeField(read_only=True, help_text="Timestamp from the source email.")
    sender = EmailThreadAddressSerializer(read_only=True, help_text="Sender from the email From header.")
    to_recipients = EmailThreadAddressSerializer(
        many=True,
        read_only=True,
        help_text="Recipients from the email To header.",
    )
    cc_recipients = EmailThreadAddressSerializer(
        many=True,
        read_only=True,
        help_text="Recipients from the email Cc header.",
    )
    sender_authenticated = serializers.BooleanField(
        read_only=True,
        help_text="Whether Mailgun authentication verified the sender domain.",
    )
    direction = serializers.ChoiceField(
        read_only=True,
        choices=[("inbound", "Inbound"), ("outbound", "Outbound")],
        help_text="Whether PostHog received or sent the message.",
    )
    content = serializers.CharField(read_only=True, allow_blank=True, help_text="Plain-text email content.")

    class Meta:
        dataclass = AccountEmailThreadMessage
        ref_name = "AccountEmailThreadMessage"
        fields = [
            "id",
            "sent_at",
            "sender",
            "to_recipients",
            "cc_recipients",
            "sender_authenticated",
            "direction",
            "content",
        ]


class CalendarSyncStatusSerializer(DataclassSerializer):
    """Sync state of one connected calendar (read-only)."""

    integration_id = serializers.IntegerField(read_only=True, help_text="Id of the google-calendar integration.")
    last_synced_at = serializers.DateTimeField(
        read_only=True, allow_null=True, help_text="When the last sync run completed; null before the first sync."
    )
    is_syncing = serializers.BooleanField(read_only=True, help_text="Whether a sync run is currently in flight.")

    class Meta:
        dataclass = CalendarSyncStatus
        ref_name = "CalendarSyncStatus"
        fields = ["integration_id", "last_synced_at", "is_syncing"]


class CalendarSyncTriggerSerializer(serializers.Serializer):
    """Request body of the calendar sync-now trigger."""

    integration_id = serializers.IntegerField(help_text="Id of the google-calendar integration to sync.")


class CalendarSyncTriggerResponseSerializer(serializers.Serializer):
    """Response of the calendar sync-now trigger."""

    status = serializers.ChoiceField(
        choices=[("started", "started"), ("already_running", "already_running")],
        help_text="'started' (a sync run began) or 'already_running' (a sync for this calendar was already in flight, so this was a no-op).",
    )


class MeetingParticipantSerializer(DataclassSerializer):
    """One attendee of a synced calendar meeting (read-only)."""

    email = serializers.CharField(read_only=True, help_text="Email address of the attendee.")
    display_name = serializers.CharField(
        read_only=True, allow_blank=True, help_text="Display name from the calendar event; may be empty."
    )
    response_status = serializers.CharField(
        read_only=True,
        help_text="The attendee's RSVP: 'needs_action', 'accepted', 'declined', or 'tentative'.",
    )
    is_organizer = serializers.BooleanField(read_only=True, help_text="Whether this attendee organized the meeting.")
    person_id = serializers.UUIDField(
        read_only=True, allow_null=True, help_text="UUID of the PostHog person resolved for this attendee, if any."
    )

    class Meta:
        dataclass = MeetingParticipantView
        ref_name = "MeetingParticipant"
        fields = ["email", "display_name", "response_status", "is_organizer", "person_id"]


class MeetingSerializer(DataclassSerializer):
    """A calendar meeting synced from a connected employee calendar (read-only)."""

    id = serializers.UUIDField(read_only=True, help_text="UUID of the meeting.")
    title = serializers.CharField(read_only=True, allow_blank=True, help_text="Meeting title; may be empty.")
    gong_url = serializers.URLField(
        read_only=True,
        allow_null=True,
        help_text="Gong call URL matched through the calendar event id; null when no Gong call is available.",
    )
    start_time = serializers.DateTimeField(read_only=True, help_text="When the meeting starts.")
    end_time = serializers.DateTimeField(read_only=True, allow_null=True, help_text="When the meeting ends.")
    organizer_email = serializers.CharField(
        read_only=True, allow_blank=True, help_text="Email address of the meeting organizer; may be empty."
    )
    status = serializers.CharField(
        read_only=True, help_text="Meeting status: 'confirmed', 'tentative', or 'cancelled'."
    )
    participants = MeetingParticipantSerializer(many=True, read_only=True, help_text="Attendees of the meeting.")

    class Meta:
        dataclass = MeetingView
        ref_name = "Meeting"
        fields = ["id", "title", "gong_url", "start_time", "end_time", "organizer_email", "status", "participants"]


class CustomPropertyReferenceSerializer(DataclassSerializer):
    """A place that uses a custom property definition (read-only)."""

    id = serializers.CharField(read_only=True, help_text="Id of the referring entity (e.g. the workflow id).")
    name = serializers.CharField(read_only=True, help_text="Display name of the referring entity.")
    status = serializers.CharField(read_only=True, help_text="Status of the referring entity (e.g. workflow status).")
    type = serializers.CharField(read_only=True, help_text="Kind of reference. Currently always 'workflow'.")

    class Meta:
        dataclass = CustomPropertyReference
        ref_name = "CustomPropertyReference"
        fields = ["id", "name", "status", "type"]


class CustomPropertySyncTriggerResponseSerializer(serializers.Serializer):
    """Response of the person/group-property sync/backfill trigger actions."""

    status = serializers.ChoiceField(
        choices=[("triggered", "triggered"), ("started", "started"), ("already_running", "already_running")],
        help_text=(
            "'triggered' (sync now started the warehouse sync), 'started' (a new backfill began), or "
            "'already_running' (a backfill for this table was already in flight, so this was a no-op)."
        ),
    )
    already_running = serializers.BooleanField(
        required=False,
        help_text="Backfill only: true when a backfill for this table was already running and this call coalesced.",
    )


class CustomPropertySyncRunListQuerySerializer(serializers.Serializer):
    search = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Match run IDs, workflow IDs, job IDs, statuses, segments, triggers, or errors.",
    )


class CustomPropertySyncRunSerializer(DataclassSerializer):
    """One warehouse-backed custom property sync run."""

    id = serializers.UUIDField(read_only=True)
    job_id = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text="Warehouse import or materialization job associated with the run, if any.",
    )
    account_segment = serializers.ChoiceField(
        choices=[("tracked", "tracked"), ("ignored", "ignored")],
        read_only=True,
        allow_null=True,
        help_text="Account segment processed by this run. Person and group property runs return null.",
    )
    sync_phase = serializers.ChoiceField(
        choices=[
            ("staging", "staging"),
            ("dispatching", "dispatching"),
            ("syncing", "syncing"),
            ("completed", "completed"),
        ],
        read_only=True,
        allow_null=True,
        help_text="Current account sync phase. Person and group property runs return null.",
    )
    attempt = serializers.IntegerField(
        read_only=True,
        allow_null=True,
        help_text="Latest Temporal activity attempt for the current account sync phase.",
    )
    workflow_id = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text="Temporal workflow identifier associated with the current account sync phase.",
    )
    workflow_run_id = serializers.UUIDField(
        read_only=True,
        allow_null=True,
        help_text="Temporal run identifier associated with the current account sync phase.",
    )
    temporal_url = serializers.URLField(
        read_only=True,
        allow_null=True,
        help_text="Staff-only link to this run in Temporal. Null for non-staff users and runs without a Temporal ID.",
    )
    trigger = serializers.CharField(
        read_only=True,
        help_text=(
            "What started the run: 'scheduled' (rode a warehouse sync), 'sync' (a warehouse sync "
            "started from the UI), 'manual' (a backfill started from the UI), or 'backfill' (the "
            "automatic backfill run when a mapping is created or re-enabled)."
        ),
    )
    status = serializers.CharField(read_only=True, help_text="Run status: 'running', 'completed', or 'failed'.")
    started_at = serializers.DateTimeField(read_only=True, allow_null=True, help_text="When the run began.")
    finished_at = serializers.DateTimeField(
        read_only=True, allow_null=True, help_text="When the run ended, or null while running."
    )
    rows_read = serializers.IntegerField(read_only=True, help_text="Warehouse rows scanned this run.")
    changed = serializers.IntegerField(read_only=True, help_text="Rows whose mapped values changed since the last run.")
    existing = serializers.IntegerField(
        read_only=True,
        help_text="Changed rows that matched an existing account, person, or group.",
    )
    produced = serializers.IntegerField(
        read_only=True, help_text="Property updates written or produced to the ingestion pipeline."
    )
    skipped_missing_person = serializers.IntegerField(
        read_only=True,
        help_text="Changed rows skipped because no existing account, person, or group matched the key column value.",
    )
    error = serializers.CharField(
        read_only=True, allow_null=True, help_text="Error summary if the run failed, else null."
    )
    created_at = serializers.DateTimeField(read_only=True, help_text="When the run row was recorded.")

    class Meta:
        dataclass = CustomPropertySyncRunView
        ref_name = "CustomPropertySyncRun"
        fields = [
            "id",
            "job_id",
            "account_segment",
            "sync_phase",
            "attempt",
            "workflow_id",
            "workflow_run_id",
            "temporal_url",
            "trigger",
            "status",
            "started_at",
            "finished_at",
            "rows_read",
            "changed",
            "existing",
            "produced",
            "skipped_missing_person",
            "error",
            "created_at",
        ]


class CustomPropertySourceSerializer(DataclassSerializer):
    """Binds warehouse columns to a custom property definition. Account sources read a materialized
    view column and sync onto matching accounts; person and group sources read either an imported
    warehouse table or a materialized view, and sync onto matching persons or groups on every
    warehouse run of what they read."""

    id = serializers.UUIDField(read_only=True)
    definition = serializers.UUIDField(
        help_text="UUID of the custom property definition this source feeds. One source per definition."
    )
    saved_query = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text=(
            "UUID of the data-warehouse saved query to read from. Required for an account source. For a "
            "person or group source it must be a materialized view, and is one of the two binding "
            "options. Mutually exclusive with external_data_schema."
        ),
    )
    external_data_schema = serializers.UUIDField(
        required=False,
        allow_null=True,
        help_text=(
            "Person and group sources only: UUID of the warehouse schema (an imported table) to read "
            "from. Mutually exclusive with saved_query; a person or group source sets exactly one."
        ),
    )
    source_column = serializers.CharField(
        max_length=400,
        required=False,
        allow_null=True,
        help_text="Account sources only: column in the view whose value is written to the property.",
    )
    column_property_map = serializers.JSONField(
        required=False,
        allow_null=True,
        help_text=(
            "Person and group sources only: {warehouse_column: property_name} mapping the columns this "
            "source writes onto the person or group."
        ),
    )
    column_descriptions = serializers.JSONField(
        required=False,
        allow_null=True,
        help_text=(
            "Person and group sources only: {warehouse_column: description} giving each mapped column a "
            "human-facing description, seeded from the warehouse column's information_schema "
            "description. Optional per column. Create-only."
        ),
    )
    key_column = serializers.CharField(
        max_length=400,
        help_text=(
            "Column whose value identifies the target: an account's external_id for account sources, "
            "the person's distinct_id for person sources, or the group key for group sources."
        ),
    )
    is_enabled = serializers.BooleanField(
        required=False,
        default=True,
        help_text=(
            "Whether the source syncs. Auto-disabled after repeated failures or a missing view; "
            "re-enabling resets the failure count."
        ),
    )
    consecutive_failures = serializers.IntegerField(
        read_only=True, help_text="Consecutive failed sync runs; the source auto-disables at the cap."
    )
    last_synced_at = serializers.DateTimeField(
        read_only=True, allow_null=True, help_text="When the most recent sync run finished."
    )
    last_sync_error = serializers.CharField(
        read_only=True, allow_null=True, help_text="Error summary from the last run, or null if it succeeded."
    )
    created_at = serializers.DateTimeField(read_only=True)
    created_by = serializers.IntegerField(read_only=True, allow_null=True)
    updated_at = serializers.DateTimeField(read_only=True, allow_null=True)
    sync_frequency_interval_seconds = serializers.FloatField(
        read_only=True,
        allow_null=True,
        help_text=(
            "Person and group sources only: how often the bound table or view runs, in seconds. Null "
            "for account sources, or when the schedule is unavailable — including a view whose "
            "frequency is set on its data-modeling DAG."
        ),
    )
    next_sync_at = serializers.DateTimeField(
        read_only=True,
        allow_null=True,
        help_text=(
            "Person and group sources only: approximate time of the next scheduled run (last run + "
            "interval). Approximate — drifts if the schedule was paused. Null for account sources, if "
            "never run, or when the interval is unavailable."
        ),
    )
    latest_run = CustomPropertySyncRunSerializer(
        read_only=True,
        allow_null=True,
        help_text="Person and group sources only: the most recent sync/backfill run, or null if none yet.",
    )
    external_data_source = serializers.UUIDField(
        read_only=True,
        allow_null=True,
        help_text=(
            "Table-bound person and group sources only: UUID of the warehouse source owning the schema, "
            "so the UI can link to the table. Null for account sources, view-bound sources, or when "
            "unavailable."
        ),
    )
    table_name = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text=(
            "Person and group sources only: what this source reads, as it is named in HogQL — the "
            "imported table, or the view. Null for account sources or when unavailable."
        ),
    )
    saved_query_name = serializers.CharField(
        read_only=True,
        allow_null=True,
        help_text=(
            "View-bound person and group sources only: the materialized view's name, so the UI can tell "
            "a view-backed source from a table-backed one. Null for account and table-bound sources."
        ),
    )

    class Meta:
        dataclass = CustomPropertySourceView
        ref_name = "CustomPropertySource"
        fields = [
            "id",
            "definition",
            "saved_query",
            "external_data_schema",
            "source_column",
            "column_property_map",
            "column_descriptions",
            "key_column",
            "is_enabled",
            "consecutive_failures",
            "last_synced_at",
            "last_sync_error",
            "created_at",
            "created_by",
            "updated_at",
            "sync_frequency_interval_seconds",
            "next_sync_at",
            "latest_run",
            "external_data_source",
            "table_name",
            "saved_query_name",
        ]


class CustomPropertyOptionSerializer(DataclassSerializer):
    """An allowed value of a select custom property."""

    id = serializers.CharField(
        required=False,
        allow_null=True,
        help_text=(
            "Server-assigned stable id of the option. Omit for new options; send it back unchanged "
            "when editing so renames and removals can be told apart."
        ),
    )
    label = serializers.CharField(  # type: ignore[assignment]
        max_length=400,
        help_text="Display label of the option. Stored as the account's value when picked.",
    )
    color = serializers.ChoiceField(
        choices=CUSTOM_PROPERTY_OPTION_COLORS,
        help_text="Preset color token used to render the option ('preset-1' through 'preset-10').",
    )

    class Meta:
        dataclass = CustomPropertyOption
        ref_name = "CustomPropertyOption"
        fields = ["id", "label", "color"]


class CustomPropertyDefinitionSerializer(DataclassSerializer):
    """A team-scoped definition of a custom account property — the attribute side of the model.

    Holds only the property's shape (name, display type, big-number flag). Per-account values are
    stored separately, so this serializer never reads or writes account values.
    """

    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(
        max_length=400,
        help_text="Human-readable name of the custom property. Unique within the team.",
    )
    description = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Optional description of what the property represents.",
    )
    display_type = serializers.ChoiceField(
        choices=CUSTOM_PROPERTY_DISPLAY_TYPE_CHOICES,
        help_text=(
            "How the property is interpreted and rendered: 'text', 'number', 'currency', "
            "'percent', 'date', 'datetime', 'boolean', or 'select'."
        ),
    )
    target_type = serializers.ChoiceField(
        choices=[("account", "account"), ("person", "person"), ("group", "group")],
        required=False,
        default="account",
        help_text=(
            "What entity this property is attached to: 'account' (default), 'person', or 'group'. "
            "Person and group properties are populated from a warehouse schema and become usable like "
            "any other person/group property (feature flags, cohorts, insights)."
        ),
    )
    group_type_index = serializers.IntegerField(
        required=False,
        allow_null=True,
        min_value=0,
        max_value=4,
        help_text=(
            "For 'group' targets only: which group type (0-4) the property attaches to. Required when "
            "target_type is 'group'; must be omitted otherwise. Create-only."
        ),
    )
    is_big_number = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Abbreviate large numbers (e.g. 10,000 → 10K). Only applies to numeric properties.",
    )
    options = CustomPropertyOptionSerializer(
        many=True,
        required=False,
        allow_null=True,
        help_text=(
            "For select properties: the allowed options. Required (non-empty) when display_type is "
            "'select'; cleared server-side for other types."
        ),
    )
    source = CustomPropertySourceSerializer(  # type: ignore[assignment]
        read_only=True,
        allow_null=True,
        help_text="The data-warehouse view-sync binding feeding this property, or null when values are set manually.",
    )
    is_canonical = serializers.BooleanField(
        read_only=True,
        help_text=(
            "True when PostHog writes this property itself. Its name and display type are fixed — "
            "an update changing either is rejected."
        ),
    )
    created_at = serializers.DateTimeField(read_only=True)
    created_by = serializers.IntegerField(read_only=True, allow_null=True)
    updated_at = serializers.DateTimeField(read_only=True, allow_null=True)
    references = CustomPropertyReferenceSerializer(
        many=True,
        read_only=True,
        help_text="Workflows that use this property, resolved by definition id.",
    )

    def validate(self, attrs):
        # target_type and group_type_index are create-only, so only enforce the group rule on create.
        # (On a partial update DataclassSerializer fills unset fields with a sentinel, not None.)
        if self.partial:
            return attrs
        # DataclassSerializer hands us the constructed dataclass (not a dict).
        is_group = getattr(attrs, "target_type", None) == "group"
        has_index = getattr(attrs, "group_type_index", None) is not None
        if is_group and not has_index:
            raise serializers.ValidationError({"group_type_index": "Required when target_type is 'group'."})
        if not is_group and has_index:
            raise serializers.ValidationError({"group_type_index": "Only valid when target_type is 'group'."})
        return attrs

    class Meta:
        dataclass = CustomPropertyDefinitionView
        ref_name = "CustomPropertyDefinition"
        fields = [
            "id",
            "name",
            "description",
            "display_type",
            "target_type",
            "group_type_index",
            "is_big_number",
            "is_canonical",
            "options",
            "source",
            "created_at",
            "created_by",
            "updated_at",
            "references",
        ]


class CustomPropertySourceUpdateSerializer(serializers.Serializer):
    """Writable fields for updating a source. ``definition`` and ``saved_query`` are create-only, so
    they are intentionally absent — only these reach the facade's update."""

    source_column = serializers.CharField(
        max_length=400, required=False, help_text="Column in the view whose value is written to the property."
    )
    key_column = serializers.CharField(
        max_length=400, required=False, help_text="Column in the view whose value matches an account's external_id."
    )
    is_enabled = serializers.BooleanField(
        required=False, help_text="Whether the source syncs; re-enabling it resets the failure count."
    )


@extend_schema_field({"oneOf": [{"type": "string"}, {"type": "number"}, {"type": "boolean"}]})
class CustomPropertyValueField(serializers.Field):
    """A custom property value — a JSON scalar (string, number, or boolean).

    Datetimes are sent and returned as ISO-8601 strings. The concrete type a property accepts is
    set by its definition and validated server-side.
    """

    def to_internal_value(self, data):
        if data is None or isinstance(data, dict | list):
            raise serializers.ValidationError("Value must be a string, number, or boolean.")
        return data

    def to_representation(self, value):
        return value


class CustomPropertyValueWriteSerializer(serializers.Serializer):
    definition = serializers.UUIDField(
        help_text="UUID of the custom property definition whose value to set for this account."
    )
    value = CustomPropertyValueField(
        help_text=(
            "Value to store, matching the definition's type: a number for number/currency/percent, a "
            "boolean for boolean, an ISO-8601 string for date/datetime, or text for text properties."
        )
    )


class CustomPropertyValueSerializer(serializers.Serializer):
    """An account's current value for a custom property (read shape)."""

    id = serializers.UUIDField(read_only=True, help_text="Unique id of this value record.")
    account_id = serializers.UUIDField(read_only=True, help_text="Account the value belongs to.")
    definition_id = serializers.UUIDField(read_only=True, help_text="Custom property definition the value is for.")
    value = CustomPropertyValueField(read_only=True, help_text="The stored value, typed per the property's data type.")
    created_at = serializers.DateTimeField(read_only=True, help_text="When this value was set.")
    created_by_id = serializers.IntegerField(
        read_only=True, allow_null=True, help_text="Id of the user who set this value, if known."
    )


class CustomPropertyValueSuggestionSerializer(serializers.Serializer):
    """One suggested filter value for a custom property."""

    name = serializers.CharField(read_only=True, help_text="A suggested value for the custom property.")


class CustomPropertyValueSuggestionsResponseSerializer(serializers.Serializer):
    """Response shape of the custom property value-suggestions endpoint.

    Matches the contract of the shared property-values picker (``propertyDefinitionsModel``
    on the frontend), which expects ``{results: [{name}], refreshing}``.
    """

    results = CustomPropertyValueSuggestionSerializer(
        many=True, read_only=True, help_text="Suggested values matching the search input."
    )
    refreshing = serializers.BooleanField(
        read_only=True, help_text="Always false — present for compatibility with the property-values consumer."
    )


class AccountRelationshipDefinitionSerializer(DataclassSerializer):
    """A team-defined account relationship type (CSM, Onboarding manager, ...)."""

    id = serializers.UUIDField(read_only=True, help_text="Relationship definition UUID.")
    name = serializers.CharField(
        max_length=400, help_text="Human-readable name of the relationship. Unique within the team."
    )
    description = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="What this relationship means, e.g. 'The customer success manager responsible for this account'.",
    )
    is_single_holder = serializers.BooleanField(
        required=False,
        default=True,
        help_text="Whether only one user can hold this relationship per account at a time, e.g. a single CSM per account.",
    )

    class Meta:
        dataclass = AccountRelationshipDefinition
        ref_name = "AccountRelationshipDefinition"
        fields = ["id", "name", "description", "is_single_holder"]


class AccountAssignmentSerializer(DataclassSerializer):
    """A user assigned to an account relationship (read shape)."""

    id = serializers.IntegerField(read_only=True, help_text="PostHog user id of the assignee.")
    email = serializers.EmailField(read_only=True, help_text="Email of the assignee.")

    class Meta:
        dataclass = AccountAssignment
        ref_name = "AccountAssignment"
        fields = ["id", "email"]


class AccountRelationshipSerializer(DataclassSerializer):
    """One assignment of a user to an account relationship, with its effective range."""

    id = serializers.UUIDField(read_only=True, help_text="Unique id of this assignment row.")
    definition = AccountRelationshipDefinitionSerializer(
        read_only=True, help_text="The relationship type this assignment belongs to."
    )
    user = AccountAssignmentSerializer(
        read_only=True, allow_null=True, help_text="The assigned user; null when their account was deleted."
    )
    started_at = serializers.DateTimeField(read_only=True, help_text="When this assignment became effective.")
    ended_at = serializers.DateTimeField(
        read_only=True, allow_null=True, help_text="When this assignment ended; null while it is active."
    )

    class Meta:
        dataclass = AccountRelationship
        ref_name = "AccountRelationship"
        fields = ["id", "definition", "user", "started_at", "ended_at"]


class AccountRelationshipWriteSerializer(serializers.Serializer):
    """Input for assigning a user to an account relationship."""

    definition = serializers.UUIDField(help_text="Id of the relationship definition to assign.")
    user = serializers.IntegerField(
        help_text="PostHog user id of the assignee. Must be a member of the account's organization."
    )


class EventStreamSerializer(DataclassSerializer):
    """The caller's event stream — a live feed of selected accounts' events posted to a
    Slack channel of their choice. One stream per user per project."""

    id = serializers.UUIDField(read_only=True)
    enabled = serializers.BooleanField(
        required=False,
        default=False,
        help_text=(
            "Whether the stream delivers to Slack. Delivery also requires at least one event, "
            "at least one member account with an external ID, and a Slack workspace + channel."
        ),
    )
    event_names = serializers.ListField(
        child=serializers.CharField(max_length=400),
        required=False,
        default=list,
        help_text="Names of the events to stream (matched exactly). Duplicates and blanks are dropped.",
    )
    slack_integration = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="ID of the team's Slack workspace integration to deliver through.",
    )
    slack_channel_id = serializers.CharField(
        max_length=200,
        required=False,
        allow_blank=True,
        default="",
        help_text="Slack channel ID to post to (e.g. C0123ABC).",
    )
    slack_channel_name = serializers.CharField(
        max_length=200,
        required=False,
        allow_blank=True,
        default="",
        help_text="Display name of the Slack channel (e.g. #customer-events). Informational only.",
    )
    account_ids = serializers.ListField(
        child=serializers.UUIDField(),
        read_only=True,
        help_text=(
            "UUIDs of the member accounts whose users' events are streamed. "
            "Managed via the add_account/remove_account endpoints."
        ),
    )
    created_at = serializers.DateTimeField(read_only=True)
    created_by = serializers.IntegerField(read_only=True, allow_null=True)
    updated_at = serializers.DateTimeField(read_only=True, allow_null=True)

    class Meta:
        dataclass = EventStreamView
        ref_name = "EventStream"
        fields = [
            "id",
            "enabled",
            "event_names",
            "slack_integration",
            "slack_channel_id",
            "slack_channel_name",
            "account_ids",
            "created_at",
            "created_by",
            "updated_at",
        ]


class EventStreamMemberWriteSerializer(serializers.Serializer):
    """Request body for adding or removing an event-stream member account."""

    account_id = serializers.UUIDField(help_text="UUID of the account to add to or remove from the stream.")


class EventStreamTestMessageSerializer(serializers.Serializer):
    """Result of posting an event-stream test message to Slack."""

    channel_id = serializers.CharField(
        read_only=True, help_text="Slack channel ID the test message was posted to (e.g. C0123ABC)."
    )
