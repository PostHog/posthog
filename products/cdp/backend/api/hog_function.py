import json
from datetime import timedelta
from typing import Any, Optional, cast

from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.db import transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

import structlog
import posthoganalytics
from django_filters import BaseInFilter, CharFilter, FilterSet
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import OpenApiParameter, extend_schema
from opentelemetry import trace
from rest_framework import exceptions, serializers, status, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.serializers import BaseSerializer

from posthog.api.app_metrics2 import AppMetricsMixin
from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.hog_invocation_rerun import HogInvocationRerunRequestSerializer, HogInvocationRerunResponseSerializer
from posthog.api.log_entries import LogEntryMixin
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import SearchMatchTypeSerializerMixin, UserBasicSerializer
from posthog.api.utils import action, log_activity_from_viewset
from posthog.cdp.internal_events import is_managed_alert_internal_event
from posthog.cdp.services.icons import CDPIconsService
from posthog.cdp.site_functions import get_transpiled_function
from posthog.cdp.validation import (
    DATA_WAREHOUSE_SOURCES,
    HogFunctionFiltersSerializer,
    InputsSchemaItemSerializer,
    InputsSerializer,
    MappingsSerializer,
    compile_hog,
    generate_template_bytecode,
    masked_secret_input_keys,
)
from posthog.event_usage import AGENT_EVENT_SOURCES, get_event_source
from posthog.exceptions_capture import capture_exception
from posthog.helpers.impersonation import is_impersonated
from posthog.helpers.trigram_search import (
    DESCRIPTION_FIELD,
    MAX_SEARCH_LENGTH,
    NAME_FIELD,
    apply_trigram_search,
    drop_similar_when_exact_exists,
)
from posthog.models import Team
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.plugins.plugin_server_api import create_hog_invocation_test, rerun_hog_invocations

from products.cdp.backend.api.hog_function_template import HogFunctionTemplateSerializer
from products.cdp.backend.models.hog_function_template import HogFunctionTemplate
from products.cdp.backend.models.hog_functions.hog_function import (
    TYPES_THAT_CAN_RERUN,
    TYPES_WITH_EXECUTION_ORDER,
    TYPES_WITH_JAVASCRIPT_SOURCE,
    HogFunction,
    HogFunctionState,
    HogFunctionType,
)
from products.cdp.backend.models.hog_functions.hog_function_revision import HogFunctionRevision
from products.cdp.backend.models.hog_functions.utils import humanize_hog_function_type
from products.cdp.backend.models.plugin import TranspilerError

# Maximum size of HOG code as a string in bytes (100KB)
MAX_HOG_CODE_SIZE_BYTES = 100 * 1024
# Maximum number of transformation functions per team
MAX_TRANSFORMATIONS_PER_TEAM = 20
# Log transformations execute per log record; volume is orders of magnitude higher than
# events, so the enabled cap starts much lower.
MAX_LOG_TRANSFORMATIONS_PER_TEAM = 5

# Per-type caps on *enabled* functions of types that run in the ingestion hot path
MAX_ENABLED_FUNCTIONS_PER_TEAM_BY_TYPE = {
    HogFunctionType.TRANSFORMATION: MAX_TRANSFORMATIONS_PER_TEAM,
    HogFunctionType.TRANSFORMATION_LOG: MAX_LOG_TRANSFORMATIONS_PER_TEAM,
}

# Gates creation of log transformations while the feature rolls out; sync with
# FEATURE_FLAGS.LOGS_TRANSFORMATIONS on the frontend
LOGS_TRANSFORMATIONS_FEATURE_FLAG = "logs-transformations"

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)

# The config of a function: everything the draft cycle stages and publish promotes, and nothing
# else. Metadata (name, description, icon_url) and lifecycle (enabled, deleted, execution_order)
# always apply to the live row. The draft blob is a full snapshot of these fields so publish is a
# plain copy, not a merge.
DRAFT_CONTENT_FIELDS = ("hog", "inputs_schema", "inputs", "filters", "mappings", "masking")

# Compiled from the config fields above during validation, so they follow whichever row the config
# lands on and must never be written live by a draft-routed edit.
_DERIVED_CONTENT_FIELDS = frozenset({"bytecode", "transpiled"})

# `to_internal_value` re-injects these from the instance on every payload, so finding them in
# validated_data says nothing about what the caller actually asked to change.
_INJECTED_UPDATE_FIELDS = frozenset({"team", "type", "template_id"})

ENABLE_WITH_OPEN_DRAFT_MESSAGE = (
    "This function has config staged for review. Publish or discard it before enabling, so you don't "
    "turn on config nobody looked at."
)
CREATE_ENABLED_MESSAGE = (
    "Create destinations disabled: test with an invocation first, then enable with a separate update "
    "once the config looks right."
)

# The confirm token makes the publish preview structurally unskippable: only the preview mints it,
# and it signs both sides of the publish, so a valid token proves the caller saw what publishing
# would change. Signing the live timestamp too is what stops a publish from silently discarding a
# concurrent web edit: the draft is a full snapshot, so it overwrites whatever landed since.
PUBLISH_CONFIRM_TOKEN_MAX_AGE = timedelta(minutes=15)
_PUBLISH_CONFIRM_SALT = "hogfunction-publish"


def _publish_confirm_value(hog_function: HogFunction) -> str:
    draft_updated_at = hog_function.draft_updated_at.isoformat() if hog_function.draft_updated_at else ""
    updated_at = hog_function.updated_at.isoformat() if hog_function.updated_at else ""
    return f"{hog_function.id}:{draft_updated_at}:{updated_at}"


def mint_publish_confirm_token(hog_function: HogFunction) -> str:
    return TimestampSigner(salt=_PUBLISH_CONFIRM_SALT).sign(_publish_confirm_value(hog_function))


def split_content_secrets(content: dict) -> dict:
    """Move secret input values out of a config snapshot into a separate map, mutating `content`.

    Mirrors `HogFunction.move_secret_inputs` for the draft: a draft's secrets belong in
    `draft_encrypted_inputs`, never in the plaintext snapshot that feeds the API response and the
    revision history.
    """
    inputs = content.get("inputs")
    if not isinstance(inputs, dict):
        return {}
    secret_keys = {
        schema["key"]
        for schema in content.get("inputs_schema") or []
        if isinstance(schema, dict) and schema.get("secret") and "key" in schema
    }
    content["inputs"] = {key: value for key, value in inputs.items() if key not in secret_keys}
    return {key: value for key, value in inputs.items() if key in secret_keys}


def snapshot_hog_function_content(hog_function: HogFunction) -> dict:
    snapshot = {field: getattr(hog_function, field) for field in DRAFT_CONTENT_FIELDS}
    # Defensively strip: a row written before secret inputs were encrypted still has plaintext
    # values in `inputs`, and this snapshot feeds revision content, which must never carry secrets.
    split_content_secrets(snapshot)
    return snapshot


def _named_warehouse_tables(entries: Any) -> list[Any]:
    """The warehouse tables a filters blob actually names, ignoring the picker's placeholder row.

    Matches the placeholder rule `HogFunctionFiltersSerializer.validate` applies moments later
    (posthog/cdp/validation.py): it drops any entry named "Select a table" outright, regardless of
    whether that entry also carries a `table_name`. Checking `table_name` alone here would accept
    `{"name": "Select a table", "table_name": "x"}` — the serializer would still strip it a moment
    later, leaving `data_warehouse: []` stored despite this check having passed.
    """
    if not isinstance(entries, list):
        return []
    return [
        entry
        for entry in entries
        if isinstance(entry, dict) and entry.get("table_name") and entry.get("name") != "Select a table"
    ]


def _without(value: Any, keys: tuple[str, ...]) -> Any:
    return {k: v for k, v in value.items() if k not in keys} if isinstance(value, dict) else value


def _inputs_without_derived(inputs: Any) -> Any:
    if not isinstance(inputs, dict):
        return inputs
    return {key: _without(value, ("bytecode", "transpiled", "order")) for key, value in inputs.items()}


def comparable_content(content: dict) -> dict:
    """A config snapshot with the values validation derives from it dropped: filter and input
    bytecode, transpiled JS, input ordering.

    A background re-save can change those on its own without the config changing at all — most often
    `refresh_affected_hog_functions` recompiling filter bytecode after an action or cohort edit — so
    comparing them would version a plain rename.
    """
    filter_derived = ("bytecode", "bytecode_error", "transpiled")
    mappings = content.get("mappings")
    return {
        **content,
        "filters": _without(content.get("filters"), filter_derived),
        "inputs": _inputs_without_derived(content.get("inputs")),
        "masking": _without(content.get("masking"), ("bytecode",)),
        "mappings": [
            {
                **mapping,
                "filters": _without(mapping.get("filters"), filter_derived),
                "inputs": _inputs_without_derived(mapping.get("inputs")),
            }
            if isinstance(mapping, dict)
            else mapping
            for mapping in mappings
        ]
        if isinstance(mappings, list)
        else mappings,
    }


def explicit_secret_input_keys(raw_inputs: Any) -> set[str]:
    """Input keys carrying a real value in the request rather than the `{"secret": true}` marker the
    API hands back for secrets — the same test `InputsSerializer` uses to decide whether to recover
    the stored value instead."""
    if not isinstance(raw_inputs, dict):
        return set()
    return {
        key
        for key, value in raw_inputs.items()
        if isinstance(value, dict) and "value" in value and not value.get("secret")
    }


def draft_changed_fields(hog_function: HogFunction) -> list[str]:
    """Which config fields publishing this draft would change. Both sides are compared secret-free
    and without derived values, with staged secrets reported as an `inputs` change."""
    live = comparable_content(snapshot_hog_function_content(hog_function))
    draft = comparable_content(hog_function.draft or {})
    changed = [field for field in DRAFT_CONTENT_FIELDS if draft.get(field) != live.get(field)]

    staged_secrets = hog_function.draft_encrypted_inputs or {}
    live_secrets = hog_function.encrypted_inputs or {}
    if "inputs" not in changed and any(live_secrets.get(key) != value for key, value in staged_secrets.items()):
        changed.append("inputs")
    return sorted(changed)


class StaleHogFunctionUpdateError(exceptions.APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = (
        "This function changed since you previewed the publish, either the draft or the live config. "
        "Preview again to see where things stand now."
    )
    default_code = "stale_update"


class DraftExistsError(exceptions.APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = (
        "This function has an open draft. Publish or discard it first, or pass overwrite=true to "
        "replace it with the restored revision."
    )
    default_code = "draft_exists"


class HogFunctionStatusSerializer(serializers.Serializer):
    state = serializers.ChoiceField(choices=[state.value for state in HogFunctionState])
    tokens: serializers.IntegerField = serializers.IntegerField()


class HogFunctionMinimalSerializer(SearchMatchTypeSerializerMixin, serializers.ModelSerializer):
    created_by = UserBasicSerializer(read_only=True)
    status = HogFunctionStatusSerializer(read_only=True, required=False, allow_null=True)
    template = HogFunctionTemplateSerializer(read_only=True)

    class Meta:
        model = HogFunction
        fields = [
            "id",
            "type",
            "name",
            "description",
            "created_at",
            "created_by",
            "updated_at",
            "enabled",
            "hog",
            "filters",
            "icon_url",
            "template",
            "status",
            "execution_order",
            "search_match_type",
            "draft_updated_at",
        ]
        read_only_fields = fields
        extra_kwargs = {
            "draft_updated_at": {
                "help_text": "When config was last staged for review, or null when nothing is staged.",
            },
        }


class HogFunctionMaskingSerializer(serializers.Serializer):
    ttl = serializers.IntegerField(
        required=True,
        min_value=60,
        max_value=60 * 60 * 24,
        help_text="Time-to-live in seconds for the masking cache (60–86400).",
    )
    threshold = serializers.IntegerField(
        required=False, allow_null=True, help_text="Optional threshold count before masking applies."
    )
    hash = serializers.CharField(required=True, help_text="Hog expression used to compute the masking hash.")
    bytecode = serializers.JSONField(
        required=False, allow_null=True, help_text="Compiled bytecode for the hash expression. Auto-generated."
    )

    def validate(self, attrs):
        attrs["bytecode"] = generate_template_bytecode(attrs["hash"], input_collector=set())

        return super().validate(attrs)


class HogFunctionSerializer(HogFunctionMinimalSerializer):
    template = HogFunctionTemplateSerializer(read_only=True)
    base_updated_at = serializers.DateTimeField(
        write_only=True,
        required=False,
        help_text=(
            "Optimistic concurrency: the updated_at (or draft_updated_at when editing a staged draft) "
            "you last read. If the stored side is newer, the write fails with 409 instead of "
            "overwriting the concurrent edit. Omit to overwrite unconditionally."
        ),
    )
    masking = HogFunctionMaskingSerializer(
        required=False,
        allow_null=True,
        help_text="PII masking configuration with TTL, threshold, and hash expression.",
    )
    type = serializers.ChoiceField(
        choices=HogFunctionType.choices,
        required=False,
        allow_null=True,
        help_text="Function type: destination, site_destination, internal_destination, source_webhook, warehouse_source_webhook, site_app, transformation, or transformation_log.",
    )
    inputs_schema = serializers.ListField(
        child=InputsSchemaItemSerializer(required=True),
        required=False,
        help_text="Schema defining the configurable input parameters for this function.",
    )
    inputs = InputsSerializer(required=False, help_text="Values for each input defined in inputs_schema.")
    mappings = serializers.ListField(
        child=MappingsSerializer(),
        required=False,
        allow_null=True,
        help_text="Event-to-destination field mappings. Only for destination and site_destination types.",
    )
    filters = HogFunctionFiltersSerializer(
        required=False, help_text="Event filters that control which events trigger this function."
    )
    _create_in_folder = serializers.CharField(required=False, allow_blank=True, write_only=True)

    class Meta:
        model = HogFunction
        fields = [
            "id",
            "type",
            "name",
            "description",
            "created_at",
            "created_by",
            "updated_at",
            "enabled",
            "deleted",
            "hog",
            "bytecode",
            "transpiled",
            "inputs_schema",
            "inputs",
            "filters",
            "masking",
            "mappings",
            "icon_url",
            "template",
            "template_id",
            "status",
            "execution_order",
            "_create_in_folder",
            "batch_export_id",
            "search_match_type",
            "version",
            "draft",
            "draft_updated_at",
            "base_updated_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "created_by",
            "updated_at",
            "bytecode",
            "transpiled",
            "template",
            "status",
            "version",
            "draft",
            "draft_updated_at",
        ]
        extra_kwargs = {
            "hog": {
                "required": False,
                "help_text": "Source code. Hog language for most types; TypeScript for site_destination and site_app.",
            },
            "inputs_schema": {"required": False},
            "template_id": {
                "write_only": True,
                "help_text": "ID of the template to create this function from.",
            },
            "deleted": {
                "write_only": True,
                "help_text": "Soft-delete flag. Set to true to archive the function.",
            },
            "type": {"required": True},
            "name": {"help_text": "Display name for the function."},
            "description": {"help_text": "Human-readable description of what this function does."},
            "enabled": {"help_text": "Whether the function is active and processing events."},
            "icon_url": {"help_text": "URL for the function's icon displayed in the UI."},
            "execution_order": {"help_text": "Execution priority for transformations. Lower values run first."},
            "version": {"help_text": "Incremented every time the live config changes. See the revisions endpoint."},
            "draft": {
                "help_text": (
                    "Config staged for review but not live yet: a full snapshot of hog, inputs_schema, inputs, "
                    "filters, mappings and masking. Null when nothing is staged. Publish or discard it to clear."
                )
            },
            "draft_updated_at": {
                "help_text": "When config was last staged for review, or null when nothing is staged.",
            },
        }

    def _validate_template_is_creatable(self, template: HogFunctionTemplate) -> None:
        # Hidden templates are internal building blocks (e.g. the native email destination) that the
        # workflow editor renders but that are never offered as standalone destinations. Block creating a
        # function from one via this API/MCP entirely — they are not a supported destination type.
        if template.status == "hidden":
            raise serializers.ValidationError(
                {
                    "template_id": f"Template '{template.template_id}' is internal and cannot be used to create a function."
                }
            )

    def _validate_hidden_template_not_enabled(self, attrs: dict, is_create: bool) -> None:
        # Creating from a hidden template is already blocked outright. For an existing function built from
        # one (the unsupported standalone destinations this PR is about), allow disabling and deleting so it
        # can be cleaned up, but never let it stay enabled — block any update that would leave it enabled,
        # including content edits (hog/inputs/filters) that omit `enabled` while it is currently on.
        if is_create or not isinstance(self.instance, HogFunction) or attrs.get("deleted") is True:
            return
        if attrs.get("enabled", self.instance.enabled) is not True:
            return
        template = HogFunctionTemplate.get_template(self.instance.template_id) if self.instance.template_id else None
        if template is not None and template.status == "hidden":
            raise serializers.ValidationError(
                {
                    "enabled": "This function was created from an internal template and can only be disabled or deleted, not kept enabled."
                }
            )

    # NOTE: All pre-validation should be done here such as loading the template info etc.
    def to_internal_value(self, data):
        # Copy before filling in defaults below: `data` is `request.data` itself, and injecting
        # inputs/inputs_schema/filters into it made every metadata-only PATCH look to the viewset like
        # a config edit. It also means a form-encoded (immutable QueryDict) payload no longer 500s.
        data = {**data}
        self.initial_data = data
        team = self.context["get_team"]()
        is_create = self.context.get("is_create") or (
            self.context.get("view") and self.context["view"].action == "create"
        )
        instance = cast(Optional[HogFunction], self.context.get("instance", self.instance))

        # Override some default values from the instance that should always be set
        data["type"] = data.get("type", instance.type if instance else "destination")
        data["template_id"] = instance.template_id if instance else data.get("template_id")
        data["inputs_schema"] = data.get("inputs_schema", instance.inputs_schema if instance else [])
        data["inputs"] = data.get("inputs", instance.inputs if instance else {})

        # Always ensure filters is initialized as an empty object if it's null
        data["filters"] = data.get("filters", instance.filters if instance else {}) or {}

        # Set some context variables that are used in the sub validators
        self.context["function_type"] = data["type"]
        # Uncompilable filters only block saves that leave the function enabled - disabling or
        # deleting must stay possible even when e.g. the team's test account filters have since
        # gained a cohort that real-time filters can't evaluate. Coerce via BooleanField so
        # form-encoded string values ("true"/"false") are read correctly, not by Python truthiness.
        to_bool = serializers.BooleanField().to_internal_value
        deleted = to_bool(data["deleted"]) if data.get("deleted") is not None else False
        enabled = (
            to_bool(data["enabled"]) if data.get("enabled") is not None else (instance.enabled if instance else False)
        )
        self.context["function_will_be_enabled"] = False if deleted else enabled
        # Warehouse sources deliver the row under event.properties, so input templates may use the
        # `{record.x}` alias — flag it so the inputs serializer rewrites it on compile.
        self.context["is_dwh_source"] = data["filters"].get("source") in DATA_WAREHOUSE_SOURCES
        # Materialized views are a newer source than warehouse tables, so nothing was saved before
        # the consumer matched on the selected table. That lets us require a selection here, where
        # an empty list still has to mean "every table" for the older source.
        #
        # Counts entries that name a table rather than entries that exist: the filters serializer
        # drops the picker's "Select a table" placeholder, so a placeholder-only list arrives here
        # non-empty and leaves it empty, which the consumer reads as "every view".
        if (
            data["filters"].get("source") == "data-warehouse-view"
            and self.context["function_will_be_enabled"]
            and not _named_warehouse_tables(data["filters"].get("data_warehouse"))
        ):
            raise serializers.ValidationError({"filters": "Select the materialized view to trigger on."})
        self.context["encrypted_inputs"] = instance.encrypted_inputs if instance else {}

        template = None
        if data["template_id"]:
            template = HogFunctionTemplate.get_template(data["template_id"])
            if not template:
                properties = {"team_id": team.id, "template_id": data.get("template_id")}
                if instance and instance.id:
                    properties["hog_function_id"] = instance.id
                capture_exception(
                    Exception(f"No template found for id '{data['template_id']}'"), additional_properties=properties
                )

                raise serializers.ValidationError({"template_id": f"No template found for id '{data['template_id']}'"})

        if is_create:
            # Set defaults for new functions
            data["inputs_schema"] = data.get("inputs_schema") or []
            data["inputs"] = data.get("inputs") or {}
            data["mappings"] = data.get("mappings") or None

            # Handle template values
            template_id = data.get("template_id")
            if template_id:
                template = HogFunctionTemplate.objects.get(template_id=data["template_id"])
                if template:
                    self._validate_template_is_creatable(template)
                    data["hog"] = data.get("hog") or template.code
                    data["inputs_schema"] = data.get("inputs_schema") or template.inputs_schema
                    data["inputs"] = data.get("inputs") or {}
                    data["icon_url"] = data.get("icon_url") or template.icon_url
                    data["description"] = data.get("description") or template.description
                    data["name"] = data.get("name") or template.name

        return super().to_internal_value(data)

    def validate_type(self, value):
        if value == HogFunctionType.WAREHOUSE_SOURCE_WEBHOOK.value:
            raise serializers.ValidationError(
                "Cannot create or modify warehouse source webhook functions via this API."
            )

        # Ensure it is only set when creating a new function
        if self.context.get("view") and self.context["view"].action == "create":
            return value

        instance = cast(Optional[HogFunction], self.context.get("instance", self.instance))
        if instance and instance.type != value:
            raise serializers.ValidationError("Cannot modify the type of an existing function")
        return value

    def validate(self, attrs):
        team = self.context["get_team"]()
        attrs["team"] = team  # NOTE: This has to be done at this level
        hog_type = self.context["function_type"]
        is_create = self.context.get("is_create") or (
            self.context.get("view") and self.context["view"].action == "create"
        )

        if not self.context.get("allow_managed_alert_destination"):
            current_filters = self.instance.filters if isinstance(self.instance, HogFunction) else {}
            proposed_filters = attrs.get("filters", current_filters)
            current_is_managed = any(
                is_managed_alert_internal_event(event_filter.get("id"))
                for event_filter in (current_filters or {}).get("events", [])
                if isinstance(event_filter, dict)
            )
            proposed_is_managed = any(
                is_managed_alert_internal_event(event_filter.get("id"))
                for event_filter in (proposed_filters or {}).get("events", [])
                if isinstance(event_filter, dict)
            )
            if current_is_managed or proposed_is_managed:
                raise serializers.ValidationError(
                    {"filters": "Alert notification destinations are managed through the alert API."}
                )

        self._validate_hidden_template_not_enabled(attrs, bool(is_create))

        # Existing functions keep working (and can be updated/disabled) if the flag is
        # later turned off; only creation is gated.
        if is_create and hog_type == HogFunctionType.TRANSFORMATION_LOG:
            if not posthoganalytics.feature_enabled(
                LOGS_TRANSFORMATIONS_FEATURE_FLAG,
                str(team.uuid),
                groups={"organization": str(team.organization.id)},
                group_properties={
                    "organization": {
                        "id": str(team.organization.id),
                        "created_at": team.organization.created_at,
                    }
                },
                send_feature_flag_events=False,
            ):
                raise serializers.ValidationError({"type": "Log transformations are not enabled for this team."})

        # Check for transformation limit per team when the function will be enabled
        # We allow unlimited creation of disabled transformations as they don't run during ingestion
        enabled_cap = MAX_ENABLED_FUNCTIONS_PER_TEAM_BY_TYPE.get(hog_type)
        if enabled_cap is not None:
            # The cap covers the effective post-update state: restoring a soft-deleted
            # enabled function ({"deleted": false} with no "enabled" key) re-enters the
            # running set just like flipping enabled on, and must not bypass the limit.
            instance = self.instance if isinstance(self.instance, HogFunction) else None
            will_be_enabled = attrs.get("enabled", instance.enabled if instance else False)
            will_be_deleted = attrs.get("deleted", instance.deleted if instance else False)
            was_active = instance is not None and instance.enabled and not instance.deleted
            apply_limit = will_be_enabled and not will_be_deleted and not was_active

            if apply_limit:
                # Count enabled and non-deleted functions of the same type
                transformation_count = HogFunction.objects.filter(
                    team=team, type=hog_type, deleted=False, enabled=True
                ).count()

                if transformation_count >= enabled_cap:
                    raise serializers.ValidationError(
                        {
                            "type": f"Maximum of {enabled_cap} enabled {humanize_hog_function_type(hog_type)} functions allowed per team. Please contact support if you need this limit increased, or disable some existing ones."
                        }
                    )

        if attrs.get("mappings", None) is not None:
            # special case for items that migrate to mappings - we want to make sure event filters are not set
            if attrs.get("filters", None) is not None:
                attrs["filters"].pop("events", None)
                attrs["filters"].pop("actions", None)

            if hog_type not in ["site_destination", "destination"]:
                raise serializers.ValidationError({"mappings": "Mappings are only allowed for destinations."})

        if "hog" in attrs:
            # First check the raw code size before trying to compile/transpile it
            hog_code_size = len(attrs["hog"].encode("utf-8"))
            if hog_code_size > MAX_HOG_CODE_SIZE_BYTES:
                raise serializers.ValidationError(
                    {
                        "hog": f"HOG code exceeds maximum size of {MAX_HOG_CODE_SIZE_BYTES // 1024}KB. Please simplify your code or contact support if you need this limit increased."
                    }
                )

            if hog_type in TYPES_WITH_JAVASCRIPT_SOURCE:
                try:
                    # Validate transpilation using the model instance
                    attrs["transpiled"] = get_transpiled_function(
                        HogFunction(
                            team=team,
                            hog=attrs["hog"],
                            filters=attrs["filters"],
                            inputs=attrs["inputs"],
                        )
                    )
                except TranspilerError:
                    raise serializers.ValidationError({"hog": "Error in TypeScript code"})
                attrs["bytecode"] = None
            else:
                attrs["bytecode"] = compile_hog(attrs["hog"], hog_type)
                attrs["transpiled"] = None

        if is_create:
            if not attrs.get("hog"):
                raise serializers.ValidationError({"hog": "Required."})

        return attrs

    def to_representation(self, data):
        is_instance = isinstance(data, HogFunction)
        encrypted_inputs = data.encrypted_inputs or {} if is_instance else {}
        draft_encrypted_inputs = data.draft_encrypted_inputs or {} if is_instance else {}
        data = super().to_representation(data)

        inputs_schema = data.get("inputs_schema", []) or []
        inputs = data.get("inputs") or {}

        for schema in inputs_schema:
            if schema.get("secret"):
                # TRICKY: We used to store these inputs so we check both the encrypted and non-encrypted inputs
                has_value = encrypted_inputs.get(schema["key"]) or inputs.get(schema["key"])
                if has_value:
                    # Marker to indicate to the user that a secret is set
                    inputs[schema["key"]] = {"secret": True}

        data["inputs"] = inputs
        data["draft"] = self._mask_draft_secrets(data.get("draft"), draft_encrypted_inputs, encrypted_inputs)

        return data

    @staticmethod
    def _mask_draft_secrets(
        draft: Optional[dict], draft_encrypted_inputs: dict, encrypted_inputs: dict
    ) -> Optional[dict]:
        # A draft's secret values live in draft_encrypted_inputs (falling back to the live ones on
        # publish), so the snapshot itself carries no secrets to hide — but the reader still needs to
        # know a secret is set. Emit the same `{"secret": true}` marker the live inputs use, on a copy
        # so the instance's stored draft is left alone.
        if not isinstance(draft, dict):
            return draft
        inputs = dict(draft.get("inputs") or {})
        for schema in draft.get("inputs_schema") or []:
            key = schema.get("key") if isinstance(schema, dict) else None
            if not key or not schema.get("secret"):
                continue
            if draft_encrypted_inputs.get(key) or encrypted_inputs.get(key) or inputs.get(key):
                inputs[key] = {"secret": True}
        return {**draft, "inputs": inputs}

    def create(self, validated_data: dict, *args, **kwargs) -> HogFunction:
        request = self.context["request"]
        validated_data["created_by"] = request.user

        template_id = validated_data.get("template_id")
        if template_id:
            db_template = HogFunctionTemplate.objects.get(template_id=template_id)
            if not db_template:
                raise serializers.ValidationError({"template_id": f"No template found for id '{template_id}'"})
            validated_data["hog_function_template"] = db_template

        # Handle execution_order for types that run sequentially during ingestion
        if validated_data.get("type") in TYPES_WITH_EXECUTION_ORDER:
            requested_order = validated_data.get("execution_order")

            # For transformations, we need to determine the execution_order
            if requested_order is None:
                # If no order specified, add at the end
                highest_order = self._get_highest_execution_order(validated_data["team"].id, validated_data["type"])
                validated_data["execution_order"] = highest_order + 1

            # Create the function with the execution_order
            return super().create(validated_data=validated_data)
        else:
            # For non-transformation types, just create normally
            return super().create(validated_data=validated_data)

    def _get_highest_execution_order(self, team_id: int, hog_type: str) -> int:
        """Get the highest execution_order among functions of the same type in a team."""
        highest_order = (
            HogFunction.objects.filter(team_id=team_id, type=hog_type, deleted=False)
            .order_by("-execution_order")
            .values_list("execution_order", flat=True)
            .first()
        )
        return highest_order or 0

    def update(self, instance: HogFunction, validated_data: dict, *args, **kwargs) -> HogFunction:
        # Handle undeletion or re-enabling by placing at the end when needed
        if instance.type in TYPES_WITH_EXECUTION_ORDER and (
            (instance.deleted and validated_data.get("deleted") is False)
            or (
                not instance.enabled
                and validated_data.get("enabled") is True
                and "execution_order" not in validated_data
            )
        ):
            highest_order = self._get_highest_execution_order(instance.team_id, instance.type)
            validated_data["execution_order"] = highest_order + 1

        # Standard update
        res: HogFunction = super().update(instance, validated_data)

        if res.enabled and res.status.get("state", 0) == HogFunctionState.DISABLED.value:
            res.set_function_status(HogFunctionState.DEGRADED.value)

        return res


class HogFunctionInvocationSerializer(serializers.Serializer):
    configuration = HogFunctionSerializer(
        write_only=True, required=False, help_text="Full function configuration to test. Omit when use_draft is true."
    )
    use_draft = serializers.BooleanField(
        default=False,
        write_only=True,
        help_text=(
            "Test the function's staged draft instead of passing a configuration. Staged secret inputs "
            "are used; secrets the draft doesn't change fall back to the live values. 400 when nothing "
            "is staged."
        ),
    )
    globals = serializers.DictField(
        write_only=True, required=False, help_text="Mock global variables available during test invocation."
    )
    clickhouse_event = serializers.DictField(
        write_only=True, required=False, help_text="Mock ClickHouse event data to test the function with."
    )
    mock_async_functions = serializers.BooleanField(
        default=True,
        write_only=True,
        help_text="When true (default), async functions like fetch() are simulated.",
    )
    status = serializers.CharField(read_only=True, help_text="Invocation result status.")
    logs = serializers.ListField(read_only=True, help_text="Execution logs from the test invocation.")
    invocation_id = serializers.CharField(
        required=False, allow_null=True, help_text="Optional invocation ID for correlation."
    )


class HogFunctionRevisionBasicSerializer(serializers.ModelSerializer):
    # allow_null: the first tracked write bootstraps a snapshot of the pre-existing live config,
    # which has no author.
    created_by = UserBasicSerializer(read_only=True, allow_null=True)

    class Meta:
        model = HogFunctionRevision
        fields = ["version", "created_at", "created_by"]
        read_only_fields = fields


class HogFunctionRevisionSerializer(HogFunctionRevisionBasicSerializer):
    class Meta(HogFunctionRevisionBasicSerializer.Meta):
        fields = [*HogFunctionRevisionBasicSerializer.Meta.fields, "content"]
        read_only_fields = fields


class HogFunctionRevisionRestoreRequestSerializer(serializers.Serializer):
    overwrite = serializers.BooleanField(
        default=False,
        help_text=(
            "Replace the open staged draft with this revision's config. Without it, restoring while a "
            "draft is open returns 409."
        ),
    )


class HogFunctionPublishRequestSerializer(serializers.Serializer):
    confirm = serializers.BooleanField(
        default=False,
        help_text=(
            "False (default) previews the publish: returns which config fields would change without "
            "changing anything. True applies the staged draft to the live function."
        ),
    )
    confirm_token = serializers.CharField(
        required=False,
        help_text=(
            "From the preview response, and required when confirm=true on an enabled function. Expires "
            "after 15 minutes, and any edit to the draft or the live config invalidates it (409), so you "
            "always publish the exact draft you previewed."
        ),
    )


class HogFunctionPublishResponseSerializer(serializers.Serializer):
    published = serializers.BooleanField(help_text="Whether the draft was applied to the live function.")
    draft_updated_at = serializers.DateTimeField(
        allow_null=True,
        help_text="The staged draft's timestamp, for reference; publishing is confirmed via confirm_token.",
    )
    confirm_token = serializers.CharField(
        allow_null=True,
        help_text="Echo this back with confirm=true to publish the previewed draft. Only set on previews.",
    )
    changed_fields = serializers.ListField(
        child=serializers.CharField(),
        allow_null=True,
        help_text=(
            "Config fields publishing would change (hog, inputs_schema, inputs, filters, mappings, masking). "
            "Only set on previews."
        ),
    )
    function = HogFunctionSerializer(
        required=False,
        allow_null=True,
        help_text="The function after publishing (only set when published=true).",
    )


class HogFunctionRearrangeSerializer(serializers.Serializer):
    orders = serializers.DictField(
        child=serializers.IntegerField(),
        help_text="Map of hog function UUIDs to their new execution_order values.",
    )


class HogFunctionMaskedSecretSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="ID of the hog function.")
    name = serializers.CharField(help_text="Name of the hog function.")
    type = serializers.CharField(help_text="Hog function type, for example 'destination'.")
    enabled = serializers.BooleanField(help_text="Whether the hog function is enabled.")
    input_keys = serializers.ListField(
        child=serializers.CharField(),
        help_text="Keys of the live secret inputs to enter again. Only keys are returned, never values.",
    )
    draft_input_keys = serializers.ListField(
        child=serializers.CharField(),
        help_text="Keys of the staged draft's secret inputs to enter again. Only keys are returned.",
    )


class CommaSeparatedListFilter(BaseInFilter, CharFilter):
    pass


class HogFunctionFilterSet(FilterSet):
    type = CommaSeparatedListFilter(field_name="type", lookup_expr="in")

    class Meta:
        model = HogFunction
        fields = ["type", "enabled", "id", "created_by", "created_at", "updated_at"]


@extend_schema(tags=["hog_functions"], extensions={"x-product": "cdp"})
class HogFunctionViewSet(
    TeamAndOrgViewSetMixin,
    LogEntryMixin,
    AppMetricsMixin,
    ForbidDestroyModel,
    viewsets.ModelViewSet,
):
    scope_object = "hog_function"
    scope_object_read_actions = [
        "list",
        "retrieve",
        "logs",
        "metrics",
        "metrics_totals",
        "revisions",
        "revision_detail",
        "masked_secrets",
    ]
    scope_object_write_actions = [
        "create",
        "update",
        "partial_update",
        "invocations",
        "rearrange",
        "rerun",
        "publish",
        "discard_draft",
        "restore_revision",
    ]
    queryset = HogFunction.objects.all()
    filter_backends = [DjangoFilterBackend]
    filterset_class = HogFunctionFilterSet
    log_source = "hog_function"
    app_source = "hog_function"

    def dangerously_get_required_scopes(self, request, view) -> Optional[list[str]]:
        # Rerun re-executes stored invocations — it replays up to 30 days of
        # persisted event/person/group data through the current (possibly
        # reconfigured) function. A `hog_function:write`-only token could use
        # that to route historical data it can't otherwise read to a destination
        # it controls, so gate rerun on person:read + group:read on top of write
        # — the same data-read scopes the invocation-inspection paths require.
        # (`hog_function:read` would be a no-op since :write already satisfies it.)
        if self.action == "rerun":
            return ["hog_function:write", "person:read", "group:read"]
        return None

    def get_serializer_class(self) -> type[BaseSerializer]:
        if self.action == "list":
            # Use full serializer (including inputs, mappings, etc.) when ?full=true
            if self.request.GET.get("full") == "true":
                return HogFunctionSerializer
            return HogFunctionMinimalSerializer
        return HogFunctionSerializer

    @tracer.start_as_current_span("HogFunctionViewSet.list")
    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        response = super().list(request, *args, **kwargs)
        if request.query_params.get("search"):
            data = response.data if isinstance(response.data, dict) else {}
            results_len = data.get("count", len(data.get("results", [])))
            span = trace.get_current_span()
            span.set_attribute("hog_function.search.result_count", results_len)
            span.set_attribute("hog_function.search.empty", results_len == 0)
        return response

    @staticmethod
    @tracer.start_as_current_span("HogFunctionViewSet._apply_search")
    def _apply_search(queryset: QuerySet, search: str) -> QuerySet:
        return apply_trigram_search(
            queryset,
            search,
            span_prefix="hog_function.search",
            fields=(NAME_FIELD, DESCRIPTION_FIELD),
            tiebreakers=("name",),
        )

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet:
        queryset = queryset.exclude(type=HogFunctionType.WAREHOUSE_SOURCE_WEBHOOK.value)

        if not (self.action == "partial_update" and self.request.data.get("deleted") is False):
            # We only want to include deleted functions if we are un-deleting them
            queryset = queryset.filter(deleted=False)

        if self.action == "list":
            search = self.request.GET.get("search")
            if search:
                if len(search) > MAX_SEARCH_LENGTH:
                    raise serializers.ValidationError(
                        {"search": f"Search query must be {MAX_SEARCH_LENGTH} characters or fewer."}
                    )
                queryset = self._apply_search(queryset, search)
            else:
                queryset = queryset.order_by("execution_order", "-updated_at")

        final_filter_groups = []

        if self.request.GET.get("filter_groups"):
            try:
                filter_groups = json.loads(self.request.GET["filter_groups"])
                if not isinstance(filter_groups, list):
                    raise ValueError("filter_groups must be a list")

                for filter_group in filter_groups:
                    final_filter_groups.append(filter_group)

            except (ValueError, KeyError, TypeError):
                raise exceptions.ValidationError({"filter_groups": "Invalid filter_groups"})

        if self.request.GET.get("filters"):
            try:
                filters = json.loads(self.request.GET["filters"])
                final_filter_groups.append(filters)
            except (ValueError, KeyError, TypeError):
                raise exceptions.ValidationError({"filters": "Invalid filters"})

        if final_filter_groups:
            combined_q = Q()

            for filter_group in final_filter_groups:
                if filter_group:
                    combined_q |= Q(filters__contains=filter_group)

            queryset = queryset.filter(combined_q)

        return queryset

    def filter_queryset(self, queryset: QuerySet) -> QuerySet:
        return drop_similar_when_exact_exists(super().filter_queryset(queryset))

    @action(detail=False, methods=["GET"])
    def icons(self, request: Request, *args, **kwargs):
        query = request.GET.get("query")
        if not query:
            return Response([])

        icons = CDPIconsService().list_icons(
            query, icon_url_base="/api/projects/@current/hog_functions/icon/?id=", team_id=self.team_id
        )

        return Response(icons)

    @action(detail=False, methods=["GET"])
    def icon(self, request: Request, *args, **kwargs):
        id = request.GET.get("id")
        if not id:
            raise serializers.ValidationError("id is required")

        icon_service = CDPIconsService()

        return icon_service.get_icon_http_response(id, team_id=self.team_id)

    @extend_schema(
        operation_id="hog_functions_masked_secrets_retrieve",
        responses=HogFunctionMaskedSecretSerializer(many=True),
    )
    @action(detail=False, methods=["GET"], pagination_class=None, filter_backends=[])
    def masked_secrets(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Hog functions storing the secret mask in place of a real credential.

        Such a function authenticates against nothing and fails every send. The original value
        cannot be restored from our side, so each listed input has to be entered again.
        """
        affected = []
        # Access filtering runs only for the `list` action, and a detail route relies on object
        # permissions instead - a collection action like this one gets neither. Without this a
        # member restricted to some functions would learn which of the others hold a broken
        # credential, and under which input keys.
        accessible = self.user_access_control.filter_queryset_by_access_level(
            self.get_queryset(), resource="hog_function"
        )
        # Only the columns the scan reads: the rest include large text/JSON fields (hog, bytecode,
        # transpiled, draft, ...) that would be transferred and deserialized for every row for nothing.
        scan = accessible.only("id", "name", "type", "enabled", "encrypted_inputs", "draft_encrypted_inputs")
        for hog_function in scan.order_by("-updated_at").iterator(chunk_size=100):
            input_keys = masked_secret_input_keys(hog_function.encrypted_inputs)
            draft_input_keys = masked_secret_input_keys(hog_function.draft_encrypted_inputs)
            if not input_keys and not draft_input_keys:
                continue
            affected.append(
                {
                    "id": hog_function.id,
                    "name": hog_function.name or "",
                    "type": hog_function.type or "",
                    "enabled": hog_function.enabled,
                    "input_keys": input_keys,
                    "draft_input_keys": draft_input_keys,
                }
            )

        return Response(HogFunctionMaskedSecretSerializer(affected, many=True).data)

    def _draft_test_configuration(self, hog_function: Optional[HogFunction]) -> dict:
        """The staged draft as a test-invocable configuration: live config with the draft's content
        fields on top, staged secrets rehydrated in plaintext so the test exercises what publish
        would ship. Secrets the draft doesn't stage stay as `{"secret": true}` markers, which
        validation recovers from the live encrypted inputs."""
        if hog_function is None or not hog_function.draft:
            raise exceptions.ValidationError({"use_draft": "This function has no staged draft to test."})

        serialized = self.get_serializer(hog_function).data
        draft = serialized.get("draft") or {}
        configuration = {**serialized, **{field: draft[field] for field in DRAFT_CONTENT_FIELDS if field in draft}}
        inputs = dict(configuration.get("inputs") or {})
        inputs.update(hog_function.draft_encrypted_inputs or {})
        configuration["inputs"] = inputs
        return configuration

    @extend_schema(
        request=HogFunctionInvocationSerializer,
        responses={200: HogFunctionInvocationSerializer},
    )
    @action(detail=True, methods=["POST"])
    def invocations(self, request: Request, *args, **kwargs):
        try:
            hog_function = self.get_object()
        except Exception:
            hog_function = None

        data = request.data
        if data.get("use_draft"):
            data = {**data, "configuration": self._draft_test_configuration(hog_function)}
        elif "configuration" not in data:
            raise exceptions.ValidationError({"configuration": "Required unless use_draft is true."})

        serializer = HogFunctionInvocationSerializer(
            data=data, context={**self.get_serializer_context(), "instance": hog_function}
        )
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)

        configuration = serializer.validated_data["configuration"]
        # Remove the team from the config
        configuration.pop("team")

        res = create_hog_invocation_test(
            team_id=self.team_id,
            hog_function_id=str(hog_function.id) if hog_function else "new",
            payload=serializer.validated_data,
        )

        if res.status_code != 200:
            return Response({"status": "error"}, status=res.status_code)

        return Response(res.json())

    @extend_schema(
        request=HogInvocationRerunRequestSerializer,
        responses={200: HogInvocationRerunResponseSerializer, 400: HogInvocationRerunResponseSerializer},
    )
    @action(detail=True, methods=["POST"])
    def rerun(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        """
        Rerun past invocations of this hog function from their stored payloads.

        The CDP worker reads matching rows from the `hog_invocation_results`
        ClickHouse table, rehydrates the invocation from the stored
        `invocation_globals`, and re-enqueues onto cyclotron. Each rerun
        run reuses the original `invocation_id` with `is_retry=1` set on the
        new lifecycle row so the UI can surface that it was a rerun.

        Only types a cyclotron worker executes (`TYPES_THAT_CAN_RERUN`) can be
        rerun: rerun re-enqueues onto the cyclotron hog queue, and other types
        run elsewhere (source webhooks inline in the cdp-api HTTP handler,
        transformations during ingestion, `site_*` transpiled to client-side
        JS). A re-enqueued invocation of one of those would never drain and
        wedges the partition, so a rerun of a non-rerunnable type is rejected
        with a 400 here. A disabled function is rejected the same way: the
        worker skips its invocations, so the rerun could never execute.

        Because rerun replays historical event/person/group data, it requires
        `person:read` and `group:read` on top of `hog_function:write`.
        """
        hog_function = self.get_object()

        if hog_function.type not in TYPES_THAT_CAN_RERUN:
            return Response(
                {
                    "queued_count": 0,
                    "skipped_count": 0,
                    "detail": f"Re-runs aren't supported for '{hog_function.type}' functions.",
                },
                status=400,
            )

        # The worker skips invocations of disabled functions, so an enqueued re-run could never execute.
        if not hog_function.enabled:
            raise serializers.ValidationError("This function is disabled. Enable it to re-run invocations.")

        serializer = HogInvocationRerunRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # `serializer.data` runs `to_representation`, which converts the
        # `DateTimeField`s on `filter.window_start` / `filter.window_end` to
        # ISO-8601 strings — `requests.post(json=...)` can't serialize raw
        # `datetime` objects, so passing `validated_data` would 500 every
        # filter-mode rerun before the request even left Django.
        res = rerun_hog_invocations(
            team_id=self.team_id,
            function_kind="hog_function",
            function_id=str(hog_function.id),
            payload=serializer.data,
        )

        if res.status_code != 200:
            return Response(
                {"queued_count": 0, "skipped_count": 0, "detail": res.text},
                status=res.status_code,
            )

        return Response(res.json())

    def perform_create(self, serializer):
        # base_updated_at is an update-only concurrency guard; there is nothing to race on a create.
        serializer.validated_data.pop("base_updated_at", None)
        # An agent-created destination starts disabled: create, test, then enable in a separate call
        # once the config looks right. Scoped like the draft cycle — other types (e.g. the alert
        # recipe's internal_destination) create as sent, and a null type behaves as a destination
        # everywhere else in this file.
        if (
            serializer.validated_data.get("enabled")
            and (serializer.validated_data.get("type") or HogFunctionType.DESTINATION) == HogFunctionType.DESTINATION
            and self._is_agent_request(self.request)
        ):
            raise exceptions.ValidationError({"enabled": CREATE_ENABLED_MESSAGE})
        serializer.save()
        log_activity_from_viewset(
            self,
            serializer.instance,
            name=serializer.instance.name,
            detail_type=humanize_hog_function_type(serializer.instance.type),
        )

    @staticmethod
    def _is_agent_request(request: Request) -> bool:
        return get_event_source(request) in AGENT_EVENT_SOURCES

    def _sent_content_fields(self) -> set[str]:
        # The config fields the caller actually asked to change. `to_internal_value` re-injects
        # inputs/inputs_schema/filters from the instance on every payload, so validated_data can't
        # tell us this — and trusting it would let a hog-only edit overwrite already-staged inputs
        # with the live ones.
        return set(self.request.data.keys()) & set(DRAFT_CONTENT_FIELDS)

    def _should_route_to_draft(self, serializer: BaseSerializer) -> bool:
        # Guardrail for agent callers (MCP and the surfaces that wrap it; the web builder and raw API
        # keys are unaffected). An agent editing a destination that is running right now stages a
        # draft for a human to publish instead of changing what workers execute on the spot.
        # Destinations only for now: transformations add execution-order semantics, site_* types add
        # transpiled-JS concerns, and internal_destination rows are written by other products' code
        # rather than by agents.
        if not self._is_agent_request(self.request):
            return False
        instance = serializer.instance
        if not isinstance(instance, HogFunction) or not instance.enabled:
            return False
        if instance.type != HogFunctionType.DESTINATION:
            return False
        return bool(self._sent_content_fields())

    def _write_draft(
        self, instance: HogFunction, locked: HogFunction, serializer: BaseSerializer, validated_content: dict
    ) -> None:
        # The draft is always a full config snapshot (live config as the base, staged draft on top,
        # this edit's validated fields last) so publish is a plain copy with no merge logic.
        # validated_content is passed in because the caller's metadata save clears validated_data.
        sent = self._sent_content_fields()
        draft = {**snapshot_hog_function_content(locked), **(locked.draft or {})}
        for field in sent:
            if field in validated_content:
                draft[field] = validated_content[field]

        recovered = split_content_secrets(draft)
        staged = locked.draft_encrypted_inputs or {}
        if "inputs" in sent:
            # Validation recovers a resent `{"secret": true}` marker from the *live* encrypted inputs,
            # so a secret already staged in the draft has to win over that recovery — otherwise this
            # edit would silently revert it to the live value. Keys the draft no longer declares
            # secret drop out entirely.
            supplied = explicit_secret_input_keys(getattr(serializer, "initial_data", {}).get("inputs"))
            draft_secrets = {
                key: value if key in supplied or key not in staged else staged[key] for key, value in recovered.items()
            }
        else:
            # This edit didn't touch inputs, so whatever is already staged still applies — and with
            # nothing staged, publish recovers the live secrets.
            draft_secrets = staged

        instance.draft = draft
        instance.draft_updated_at = timezone.now()
        instance.draft_encrypted_inputs = draft_secrets or None
        instance.save(update_fields=["draft", "draft_updated_at", "draft_encrypted_inputs"])

    def _record_revision(self, instance: HogFunction, before: HogFunction, before_content: dict) -> None:
        """Version and snapshot a live config change. Runs right after the write it describes, in the
        same transaction. Comparing two *persisted* snapshots, rather than validated_data against the
        stored row, keeps a partial payload from reading as a config change; comparing them without
        derived values keeps a background bytecode recompile from reading as one either."""
        after_content = snapshot_hog_function_content(instance)
        if comparable_content(after_content) == comparable_content(before_content):
            return

        instance.version = (before.version or 0) + 1
        # queryset.update() rather than instance.save(): the bump must not fire a second worker
        # reload for a config push that already happened, and workers never read `version`.
        # nosemgrep: idor-lookup-without-team (ID from already team-scoped instance)
        HogFunction.objects.filter(pk=instance.pk).update(version=instance.version)

        # On the first tracked write, also snapshot the outgoing config so the state before any
        # tracked change is always available to roll back to (there's no backfill).
        if not HogFunctionRevision.objects.filter(hog_function=instance).exists():
            HogFunctionRevision.objects.create(
                team_id=self.team_id,
                hog_function=instance,
                version=before.version or 0,
                content=before_content,
                created_by=None,
            )
        HogFunctionRevision.objects.create(
            team_id=self.team_id,
            hog_function=instance,
            version=instance.version,
            content=after_content,
            created_by=self.request.user if self.request.user.is_authenticated else None,
        )

    def perform_update(self, serializer):
        instance_id = serializer.instance.id
        # Resolved before the write transaction so the routing decision doesn't extend the row lock.
        route_to_draft = self._should_route_to_draft(serializer)

        # Enabling with a draft open would turn on the live config while the reviewed one sits
        # unpublished. Make the caller resolve the draft first rather than picking for them.
        # Checked on the validated value: BooleanField coerces "true"/"True", and the raw payload
        # wouldn't catch those.
        if (
            serializer.validated_data.get("enabled") is True
            and isinstance(serializer.instance, HogFunction)
            and serializer.instance.draft
            and not serializer.instance.enabled
        ):
            raise exceptions.ValidationError({"enabled": ENABLE_WITH_OPEN_DRAFT_MESSAGE})

        # Optimistic concurrency, same contract as workflows: a client may send the updated_at (or
        # draft_updated_at) it last loaded as `base_updated_at`. If the stored side is strictly newer,
        # another channel wrote in between: 409 rather than silently clobbering. Omitting it keeps
        # last-writer-wins. Popped so it never reaches the model save.
        base_updated_at = serializer.validated_data.pop("base_updated_at", None)

        with transaction.atomic():
            try:
                # nosemgrep: idor-lookup-without-team (ID from already team-scoped instance; locked for the save)
                locked = HogFunction.objects.select_for_update().get(pk=instance_id)
                # nosemgrep: idor-lookup-without-team (re-fetch of already-authorized instance for activity logging)
                before_update = HogFunction.objects.get(pk=instance_id)
            except HogFunction.DoesNotExist:
                locked = None
                before_update = None

            route_to_draft = route_to_draft and locked is not None

            # Draft edits race against other draft edits, not against the live row (which they don't
            # touch), so the staleness baseline is the draft's own timestamp once a draft exists.
            guard_timestamp = locked.updated_at if locked else None
            if route_to_draft and locked and locked.draft_updated_at:
                guard_timestamp = locked.draft_updated_at
            if base_updated_at and guard_timestamp and guard_timestamp > base_updated_at:
                raise StaleHogFunctionUpdateError()
            if route_to_draft:
                assert locked is not None
                # Preserved before the metadata save clears validated_data below.
                validated_content = {
                    field: serializer.validated_data[field]
                    for field in DRAFT_CONTENT_FIELDS
                    if field in serializer.validated_data
                }
                # Metadata in the same payload still applies live. Config (and the bytecode compiled
                # from it) must not leak onto the live row — it belongs to the draft now.
                remaining = {
                    key: value
                    for key, value in serializer.validated_data.items()
                    if key not in DRAFT_CONTENT_FIELDS
                    and key not in _DERIVED_CONTENT_FIELDS
                    and key not in _INJECTED_UPDATE_FIELDS
                }
                # The save target is the locked row, never the request-start instance: a
                # ModelSerializer save writes every column, so saving the object fetched before
                # validation would write its stale config back over anything a concurrent live edit
                # committed in between. Metadata saves first — the full save would otherwise clobber
                # the draft columns _write_draft is about to fill with the locked row's pre-draft
                # values.
                serializer.instance = locked
                if remaining:
                    serializer.validated_data.clear()
                    serializer.validated_data.update({**remaining, "team": self.team})
                    serializer.save()
                self._write_draft(locked, locked, serializer, validated_content)
            else:
                before_content = snapshot_hog_function_content(locked) if locked else None
                serializer.save()
                if locked is not None and before_content is not None:
                    self._record_revision(serializer.instance, locked, before_content)

        log_activity_from_viewset(
            self,
            serializer.instance,
            activity="draft_updated" if route_to_draft else None,
            name=serializer.instance.name,
            previous=before_update,
            detail_type=humanize_hog_function_type(serializer.instance.type),
        )

    @extend_schema(request=HogFunctionPublishRequestSerializer, responses={200: HogFunctionPublishResponseSerializer})
    @action(detail=True, methods=["POST"])
    def publish(self, request: Request, *args, **kwargs):
        # Promote the staged draft to the live config. Two-step by design: a call without confirm only
        # echoes what would change, so callers — especially agents — never publish blind.
        param_serializer = HogFunctionPublishRequestSerializer(data=request.data)
        param_serializer.is_valid(raise_exception=True)

        instance = self.get_object()
        if not instance.draft:
            raise exceptions.ValidationError("This function has no staged draft to publish.")

        if not param_serializer.validated_data["confirm"]:
            return Response(
                {
                    "published": False,
                    "draft_updated_at": instance.draft_updated_at,
                    "confirm_token": mint_publish_confirm_token(instance),
                    "changed_fields": draft_changed_fields(instance),
                    "function": None,
                }
            )

        with transaction.atomic():
            # nosemgrep: idor-lookup-without-team (re-fetch of already-authorized instance, locked for update)
            locked = HogFunction.objects.select_for_update().get(pk=instance.pk)
            if not locked.draft:
                raise exceptions.ValidationError("This function has no staged draft to publish.")
            # A disabled function processes nothing, so publishing into it can't misroute traffic and
            # doesn't need the preview receipt. The preview is still offered either way.
            if locked.enabled:
                previewed_value = self._unsign_publish_confirm_token(
                    param_serializer.validated_data.get("confirm_token")
                )
                if previewed_value != _publish_confirm_value(locked):
                    raise StaleHogFunctionUpdateError()

            # nosemgrep: idor-lookup-without-team (re-fetch of already-authorized instance for activity logging)
            before_update = HogFunction.objects.get(pk=instance.pk)
            before_content = snapshot_hog_function_content(before_update)

            # The draft's own staged secrets outrank the live ones while the draft is revalidated: the
            # serializer recovers secret inputs from `instance.encrypted_inputs`, and save() re-splits
            # whatever it recovered back into that column.
            locked.encrypted_inputs = {
                **(locked.encrypted_inputs or {}),
                **(locked.draft_encrypted_inputs or {}),
            }
            # The draft goes back through the normal serializer so publish revalidates strictly and
            # recompiles bytecode — a stored blob is never trusted to be execution-ready.
            serializer = self.get_serializer(locked, data=dict(locked.draft), partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()
            self._record_revision(locked, before_update, before_content)

            locked.draft = None
            locked.draft_updated_at = None
            locked.draft_encrypted_inputs = None
            locked.save(update_fields=["draft", "draft_updated_at", "draft_encrypted_inputs"])

        log_activity_from_viewset(
            self,
            locked,
            activity="published",
            name=locked.name,
            previous=before_update,
            detail_type=humanize_hog_function_type(locked.type),
        )

        return Response(
            {
                "published": True,
                "draft_updated_at": None,
                "confirm_token": None,
                "changed_fields": None,
                "function": self.get_serializer(locked).data,
            }
        )

    @staticmethod
    def _unsign_publish_confirm_token(confirm_token: Optional[str]) -> str:
        if not confirm_token:
            raise exceptions.ValidationError(
                {
                    "confirm_token": (
                        "Required when confirming a publish. Call publish without confirm first to see "
                        "what would change and get a token."
                    )
                }
            )
        try:
            return TimestampSigner(salt=_PUBLISH_CONFIRM_SALT).unsign(
                confirm_token, max_age=PUBLISH_CONFIRM_TOKEN_MAX_AGE
            )
        except SignatureExpired:
            raise exceptions.ValidationError(
                {"confirm_token": "Expired. Preview the publish again to get a fresh token."}
            )
        except BadSignature:
            raise exceptions.ValidationError(
                {
                    "confirm_token": (
                        "Invalid. Call publish without confirm first to see what would change and get a token."
                    )
                }
            )

    @extend_schema(request=None, responses={200: HogFunctionSerializer})
    @action(detail=True, methods=["POST"])
    def discard_draft(self, request: Request, *args, **kwargs):
        # Throw away the staged draft. Idempotent: discarding when nothing is staged is a no-op.
        instance = self.get_object()
        with transaction.atomic():
            # nosemgrep: idor-lookup-without-team (re-fetch of already-authorized instance, locked for update)
            locked = HogFunction.objects.select_for_update().get(pk=instance.pk)
            # nosemgrep: idor-lookup-without-team (re-fetch of already-authorized instance for activity logging)
            before_update = HogFunction.objects.get(pk=instance.pk)
            had_draft = locked.draft is not None
            locked.draft = None
            locked.draft_updated_at = None
            locked.draft_encrypted_inputs = None
            locked.save(update_fields=["draft", "draft_updated_at", "draft_encrypted_inputs"])

        # The no-op case stays out of the audit trail: nothing was discarded.
        if had_draft:
            log_activity_from_viewset(
                self,
                locked,
                activity="draft_discarded",
                name=locked.name,
                previous=before_update,
                detail_type=humanize_hog_function_type(locked.type),
            )

        return Response(self.get_serializer(locked).data)

    @extend_schema(responses={200: HogFunctionRevisionBasicSerializer(many=True)})
    # filter_backends=[]: don't inherit the viewset's HogFunction filterset — its fields would be
    # advertised as query params in the generated contract but silently ignored here.
    @action(detail=True, methods=["GET"], filter_backends=[])
    def revisions(self, request: Request, *args, **kwargs):
        # Version history: one snapshot per live-config change, newest first. Config is fetched
        # per-version via the detail endpoint — the list stays light.
        instance = self.get_object()
        queryset = (
            HogFunctionRevision.objects.filter(hog_function=instance).order_by("-version").select_related("created_by")
        )
        page = self.paginate_queryset(queryset)
        return self.get_paginated_response(HogFunctionRevisionBasicSerializer(page, many=True).data)

    @extend_schema(
        parameters=[OpenApiParameter("version", int, OpenApiParameter.PATH, description="Function version to fetch.")],
        responses={200: HogFunctionRevisionSerializer},
        filters=False,
    )
    @action(detail=True, methods=["GET"], url_path=r"revisions/(?P<version>\d+)", filter_backends=[])
    def revision_detail(self, request: Request, version: Optional[str] = None, *args, **kwargs):
        instance = self.get_object()
        try:
            revision = HogFunctionRevision.objects.get(hog_function=instance, version=int(version or 0))
        except HogFunctionRevision.DoesNotExist:
            raise exceptions.NotFound("No such revision for this function.")
        return Response(HogFunctionRevisionSerializer(revision).data)

    @extend_schema(
        parameters=[
            OpenApiParameter("version", int, OpenApiParameter.PATH, description="Function version to restore.")
        ],
        request=HogFunctionRevisionRestoreRequestSerializer,
        responses={200: HogFunctionSerializer},
        filters=False,
    )
    @action(detail=True, methods=["POST"], url_path=r"revisions/(?P<version>\d+)/restore", filter_backends=[])
    def restore_revision(self, request: Request, version: Optional[str] = None, *args, **kwargs):
        # Rollback (or roll-forward) = copy the revision's config into the draft, then go through the
        # normal publish preview + confirm. Nothing here touches the live config, so a rollback is
        # reviewed like any other change.
        param_serializer = HogFunctionRevisionRestoreRequestSerializer(data=request.data)
        param_serializer.is_valid(raise_exception=True)

        instance = self.get_object()
        with transaction.atomic():
            # nosemgrep: idor-lookup-without-team (re-fetch of already-authorized instance, locked for update)
            locked = HogFunction.objects.select_for_update().get(pk=instance.pk)
            try:
                revision = HogFunctionRevision.objects.get(hog_function_id=locked.pk, version=int(version or 0))
            except HogFunctionRevision.DoesNotExist:
                raise exceptions.NotFound("No such revision for this function.")
            if locked.draft and not param_serializer.validated_data["overwrite"]:
                raise DraftExistsError()
            # nosemgrep: idor-lookup-without-team (re-fetch of already-authorized instance for activity logging)
            before_update = HogFunction.objects.get(pk=instance.pk)
            locked.draft = dict(revision.content)
            locked.draft_updated_at = timezone.now()
            # Revision snapshots carry no secrets, so the restored draft re-attaches from the live
            # encrypted inputs on the follow-up publish. Clearing also stops a prior draft's staged
            # secrets from bleeding into this one.
            locked.draft_encrypted_inputs = None
            locked.save(update_fields=["draft", "draft_updated_at", "draft_encrypted_inputs"])

        log_activity_from_viewset(
            self,
            locked,
            activity="revision_restored",
            name=locked.name,
            previous=before_update,
            detail_type=humanize_hog_function_type(locked.type),
        )

        return Response(self.get_serializer(locked).data)

    @extend_schema(
        request=HogFunctionRearrangeSerializer,
        responses={200: HogFunctionSerializer(many=True)},
        filters=False,
    )
    @action(methods=["PATCH"], detail=False, pagination_class=None)
    def rearrange(self, request: Request, *args, **kwargs) -> Response:
        """Update the execution order of multiple HogFunctions."""
        team = self.team
        orders: dict[str, int] = request.data.get("orders", {})

        if not orders:
            raise exceptions.ValidationError("No orders provided")

        with transaction.atomic():
            # Get all functions in a single query and validate them
            function_ids = list(orders.keys())
            functions = {
                str(f.id): f
                for f in HogFunction.objects.filter(
                    id__in=function_ids, team=team, type__in=TYPES_WITH_EXECUTION_ORDER, deleted=False
                )
            }

            # Validate all functions exist
            missing_ids = set(function_ids) - set(functions.keys())
            if missing_ids:
                raise exceptions.ValidationError(f"HogFunction with id {missing_ids.pop()} does not exist")

            # execution_order is scoped per type, so one rearrange request must stay within one type
            types = {f.type for f in functions.values()}
            if len(types) > 1:
                raise exceptions.ValidationError("Cannot rearrange functions of different types in one request")
            hog_type = types.pop()

            # Update orders and create activity logs
            from django.contrib.auth.models import AnonymousUser
            from django.utils import timezone

            current_time = timezone.now()
            user = None if isinstance(request.user, AnonymousUser) else request.user

            for function_id, function in functions.items():
                new_order = orders[function_id]
                old_order = function.execution_order

                if old_order != new_order:
                    function.execution_order = new_order
                    function.updated_at = current_time

                    log_activity(
                        organization_id=self.organization.id,
                        team_id=self.team_id,
                        user=user,
                        item_id=str(function.id),
                        was_impersonated=is_impersonated(request),
                        scope="HogFunction",
                        activity="updated",
                        detail=Detail(
                            name=function.name,
                            type=humanize_hog_function_type(function.type),
                            changes=[
                                Change(
                                    type="HogFunction",
                                    action="changed",
                                    field="priority",
                                    before=str(old_order),
                                    after=str(new_order),
                                )
                            ],
                        ),
                    )

                    function.save(update_fields=["execution_order", "updated_at"])

        # Get final ordered list in a single query
        transformations = HogFunction.objects.filter(team=team, type=hog_type, deleted=False).order_by(
            "execution_order"
        )

        serializer = self.get_serializer(transformations, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["POST"])
    def enable_backfills(self, request: Request, *args, **kwargs):
        from products.batch_exports.backend.api.batch_export import BatchExportSerializer

        hog_function = self.get_object()

        # Check if backfill is already enabled
        if hog_function.batch_export_id:
            return Response({"error": "Backfills already enabled for this function"}, status=400)

        # Only event-sourced destinations support backfills
        if hog_function.type != HogFunctionType.DESTINATION:
            return Response(
                {"error": "Backfills are only supported for destination functions."},
                status=400,
            )
        source = (hog_function.filters or {}).get("source", "events")
        if source != "events":
            return Response(
                {"error": "Backfills are only supported for event-sourced destinations."},
                status=400,
            )

        # Check feature flag for backfill-workflows-destination
        team = Team.objects.get(id=self.team_id)
        if not posthoganalytics.feature_enabled(
            "backfill-workflows-destination",
            str(team.uuid),
            groups={"organization": str(team.organization.id)},
            group_properties={
                "organization": {
                    "id": str(team.organization.id),
                    "created_at": team.organization.created_at,
                }
            },
            send_feature_flag_events=False,
        ):
            raise PermissionDenied("Backfilling Workflows is not enabled for this team.")

        # Prepare batch export data matching the frontend's structure
        batch_export_data = {
            "name": hog_function.name,
            "paused": True,
            "interval": "hour",
            "model": "events",
            "filters": hog_function.filters.get("events", []) if hog_function.filters else [],
            "destination": {
                "type": "Workflows",
                "config": {"hog_function_id": str(hog_function.id)},
            },
        }

        batch_export_serializer = BatchExportSerializer(
            data=batch_export_data, context={"team_id": self.team_id, "request": request}
        )

        if not batch_export_serializer.is_valid():
            return Response(batch_export_serializer.errors, status=400)

        batch_export = batch_export_serializer.save()

        hog_function.batch_export_id = batch_export.id
        hog_function.save(update_fields=["batch_export_id"])

        return Response({"batch_export_id": str(batch_export.id)})
