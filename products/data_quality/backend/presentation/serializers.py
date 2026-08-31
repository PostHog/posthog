"""DRF serializers for data quality checks.

Source of truth for the generated frontend and MCP types, so every field carries help_text. The
per-type ``config`` shape is validated against the registry's JSON schema rather than modeled as a
union: a new check type must not need a serializer change.
"""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field, extend_schema_serializer
from rest_framework import serializers
from rest_framework.exceptions import ErrorDetail

from posthog.api.shared import UserBasicSerializer

from ..facade import api
from ..facade.enums import CheckSeverity, CheckType, CreatedSource, SubjectType
from ..facade.models import DataQualityCheck, DataQualityCheckRun, DataQualitySuiteRun


@extend_schema_field(OpenApiTypes.OBJECT)
class CheckConfigField(serializers.JSONField):
    """Type-specific configuration. Call /check_types/ for the JSON schema of each type."""


@extend_schema_serializer(component_name="DataQualityCheck")
class DataQualityCheckSerializer(serializers.ModelSerializer):
    """The subject is implied by the URL (the parent saved query or table), never part of the body."""

    subject_type = serializers.ChoiceField(
        choices=[(t.value, t.value) for t in SubjectType],
        read_only=True,
        help_text="Kind of catalog object being checked: 'table' (a synced warehouse table) or 'view' (a saved query).",
    )
    subject_uuid = serializers.SerializerMethodField(
        help_text="Id of the table or view being checked -- the parent resource in the URL."
    )
    check_type = serializers.ChoiceField(
        choices=[(t.value, t.value) for t in CheckType],
        help_text="Which assertion to make. Determines the shape of config; see /check_types/.",
    )
    severity = serializers.ChoiceField(
        choices=[(s.value, s.value) for s in CheckSeverity],
        required=False,
        help_text="'error' failures mark the subject failing and notify; 'warn' failures only surface.",
    )
    created_source = serializers.ChoiceField(
        choices=[(s.value, s.value) for s in CreatedSource],
        required=False,
        help_text="Whether a human ('user') or an agent ('ai_generated') authored this check.",
    )
    config = CheckConfigField(
        required=False,
        help_text="Type-specific configuration, validated against the check type's JSON schema.",
    )
    tags = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Free-form string labels for grouping and filtering.",
    )
    last_status = serializers.CharField(
        read_only=True,
        help_text="Outcome of the newest run: passed, failed, errored, skipped, or empty if never run.",
    )
    last_succeeded_at = serializers.DateTimeField(
        read_only=True,
        allow_null=True,
        help_text="When the check last passed, so a failing check can say how long it has been failing. "
        "Null means it has not passed within the run retention window.",
    )
    subject_status = serializers.CharField(
        read_only=True,
        help_text="'orphaned' once the subject stops resolving. Orphaned checks are skipped, not deleted.",
    )
    owner = serializers.SerializerMethodField(help_text="Email of the human accountable for this check, or null.")
    created_by = UserBasicSerializer(read_only=True, help_text="User who first created this check.")

    class Meta:
        model = DataQualityCheck
        fields = [
            "id",
            "name",
            "description",
            "subject_type",
            "subject_uuid",
            "subject_name",
            "subject_status",
            "column_name",
            "check_type",
            "config",
            "severity",
            "enabled",
            "tags",
            "owner",
            "last_run_at",
            "last_status",
            "last_succeeded_at",
            "fingerprint",
            "created_source",
            "ai_model",
            "confidence",
            "reasoning",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "subject_name",
            "subject_status",
            "last_run_at",
            "last_status",
            "last_succeeded_at",
            "fingerprint",
            "created_by",
            "created_at",
            "updated_at",
        ]
        extra_kwargs = {
            "name": {
                "required": False,
                "help_text": "Optional identifier-safe handle, unique per project. Omit to address the check by id.",
            },
            "description": {"required": False, "help_text": "Why this check exists and what a failure means."},
            "subject_name": {"help_text": "Queryable name of the subject, refreshed on every run."},
            "column_name": {
                "required": False,
                "help_text": "Column the check applies to. Omit for table-scoped types like row_count.",
            },
            "enabled": {"required": False, "help_text": "Disabled checks are never run by any trigger."},
            "fingerprint": {
                "help_text": "sha256 of the subject, type, column, and config. Re-creating the same check upserts."
            },
            "ai_model": {"required": False, "help_text": "Model that generated the check, if AI-authored."},
            "confidence": {
                "required": False,
                "help_text": "AI author's confidence in the check, 0-1.",
                "min_value": 0.0,
                "max_value": 1.0,
            },
            "reasoning": {"required": False, "help_text": "AI author's reasoning, surfaced as review context."},
        }

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_owner(self, obj: DataQualityCheck) -> str | None:
        return obj.owner.email if obj.owner else None

    @extend_schema_field(serializers.UUIDField(allow_null=True))
    def get_subject_uuid(self, obj: DataQualityCheck) -> str | None:
        return str(obj.subject_uuid) if obj.subject_uuid else None

    def validate(self, attrs: dict) -> dict:
        def resolved(field: str) -> str:
            return attrs.get(field) or getattr(self.instance, field, None) or ""

        # The subject comes from the URL: the viewset resolves the parent and passes it in context.
        subject_type = self.context.get("subject_type") or getattr(self.instance, "subject_type", "")
        subject_uuid = self.context.get("subject_uuid") or (self.instance.subject_uuid if self.instance else None)
        try:
            api.validate_check(
                self.context["get_team"](),
                str(subject_type),
                str(subject_uuid),
                resolved("check_type"),
                resolved("column_name"),
                attrs.get("config", getattr(self.instance, "config", None) or {}),
            )
        except (api.CheckConfigError, api.SubjectUnresolvableError, api.UnknownCheckTypeError) as err:
            raise serializers.ValidationError({"config": str(err)})
        return attrs

    def update(self, instance: DataQualityCheck, validated_data: dict) -> DataQualityCheck:
        request = self.context.get("request")
        try:
            return api.edit_check(
                team=self.context["get_team"](),
                check=instance,
                editor=getattr(request, "user", None) if request else None,
                **validated_data,
            )
        except api.CheckEditConflict as conflict:
            # Rendered beside the offending fields rather than as a status code, so the editor can
            # keep the draft open and point at what to change.
            raise serializers.ValidationError(
                {field: ErrorDetail(str(conflict), code=conflict.code) for field in conflict.fields}
            )


@extend_schema_serializer(component_name="DataQualityOverviewCheck")
class DataQualityOverviewCheckSerializer(DataQualityCheckSerializer):
    """A check plus where its subject can be opened, for the project-wide list.

    The per-subject surfaces already know their parent; only this one lists checks across every
    table and view, so only this one needs to say where each subject lives. The ids are resolved
    for a whole page at once and handed in through ``subject_locations`` in the context.
    """

    subject_node_id = serializers.SerializerMethodField(
        help_text="Data modeling node of the view this check audits, or null when it is on no DAG "
        "or the subject is a table."
    )
    subject_source_id = serializers.SerializerMethodField(
        help_text="Warehouse source of the table this check audits, or null when the subject is a view."
    )
    subject_schema_id = serializers.SerializerMethodField(
        help_text="Warehouse source schema of the table this check audits, or null when the subject is a view."
    )

    class Meta(DataQualityCheckSerializer.Meta):
        fields = [
            *DataQualityCheckSerializer.Meta.fields,
            "subject_node_id",
            "subject_source_id",
            "subject_schema_id",
        ]

    def _location(self, obj: DataQualityCheck) -> api.SubjectLocation:
        locations: dict[api.SubjectKey, api.SubjectLocation] = self.context.get("subject_locations") or {}
        key = api.SubjectKey(subject_type=SubjectType(obj.subject_type), subject_uuid=str(obj.subject_uuid))
        return locations.get(key) or api.SubjectLocation()

    @extend_schema_field(serializers.UUIDField(allow_null=True))
    def get_subject_node_id(self, obj: DataQualityCheck) -> str | None:
        return self._location(obj).node_id

    @extend_schema_field(serializers.UUIDField(allow_null=True))
    def get_subject_source_id(self, obj: DataQualityCheck) -> str | None:
        return self._location(obj).source_id

    @extend_schema_field(serializers.UUIDField(allow_null=True))
    def get_subject_schema_id(self, obj: DataQualityCheck) -> str | None:
        return self._location(obj).schema_id


@extend_schema_serializer(component_name="DataQualityCheckRun")
class DataQualityCheckRunSerializer(serializers.ModelSerializer):
    status = serializers.CharField(read_only=True, help_text="passed, failed, errored, or skipped.")
    # Declared rather than derived: the model field carries no choices, so the schema would otherwise
    # publish check_type as a bare string.
    check_type = serializers.ChoiceField(
        choices=[(t.value, t.value) for t in CheckType],
        read_only=True,
        help_text="Which assertion this run made.",
    )
    check_config = CheckConfigField(
        read_only=True,
        allow_null=True,
        help_text="Config this run executed, snapshotted so an edit to the check cannot rewrite history. "
        "Null for runs recorded before snapshots existed -- unknown, not 'same as the check has now'.",
    )
    check_severity = serializers.ChoiceField(
        choices=[(s.value, s.value) for s in CheckSeverity],
        read_only=True,
        allow_null=True,
        help_text="Severity this run was judged at. Null for runs recorded before snapshots existed.",
    )

    class Meta:
        model = DataQualityCheckRun
        fields = [
            "id",
            "quality_check",
            "suite_run",
            "subject_type",
            "subject_uuid",
            "subject_name",
            "check_type",
            "column_name",
            "check_config",
            "check_severity",
            "status",
            "failed_row_count",
            "observed_value",
            "compiled_query",
            "error",
            "duration_ms",
            "started_at",
            "finished_at",
            "created_at",
        ]
        read_only_fields = fields
        extra_kwargs = {
            "failed_row_count": {"help_text": "Rows violating the assertion. Null for bounds checks like row_count."},
            "observed_value": {"help_text": "The check's headline number, recorded on passes too."},
            "compiled_query": {"help_text": "The HogQL that ran. Re-run it to see the offending rows."},
            "error": {"help_text": "Compilation or execution failure, when status is 'errored'."},
        }


@extend_schema_serializer(component_name="DataQualitySuiteRun")
class DataQualitySuiteRunSerializer(serializers.ModelSerializer):
    status = serializers.CharField(
        read_only=True, help_text="running, completed, failed, or empty (nothing matched the trigger)."
    )
    trigger = serializers.CharField(read_only=True, help_text="manual, materialization, or source_sync.")
    subject_type = serializers.SerializerMethodField(
        help_text="'table' or 'view' when the run targets exactly one subject, including a run of a "
        "single check on that subject; null for a run spanning several subjects."
    )

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_subject_type(self, obj: DataQualitySuiteRun) -> str | None:
        # The model stores "" for a run that is not scoped to a single subject; the response schema
        # only permits table/view, so surface the unscoped case as null rather than a blank string.
        return obj.subject_type or None

    class Meta:
        model = DataQualitySuiteRun
        fields = [
            "id",
            "trigger",
            "status",
            "subject_type",
            "subject_uuid",
            "workflow_id",
            "checks_passed",
            "checks_failed",
            "checks_errored",
            "checks_skipped",
            "started_at",
            "finished_at",
            "error",
            "created_at",
        ]
        read_only_fields = fields


@extend_schema_serializer(component_name="DataQualitySubjectHealth")
class SubjectHealthSerializer(serializers.Serializer):
    """Per-subject rollup, the same rule the information_schema.data_quality_health table uses."""

    subject_type = serializers.CharField(help_text="'table' or 'view'.")
    subject_uuid = serializers.CharField(help_text="Id of the table or view.")
    health = serializers.CharField(
        help_text="failing (an error-severity check failed), erroring (a check could not run), "
        "warn (only warn-severity failures), healthy, or unknown (nothing has run yet)."
    )
    checks_total = serializers.IntegerField(help_text="How many enabled, non-deleted checks cover this subject.")
    checks_failing = serializers.IntegerField(help_text="How many of those checks last reported a failure.")


@extend_schema_serializer(component_name="DataQualityRunRequest")
class DataQualityRunRequestSerializer(serializers.Serializer):
    """What to run in a project-wide suite run."""

    check_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        help_text="Ids of the checks to run. Omit to run every enabled check in the project.",
    )


@extend_schema_serializer(component_name="DataQualityGateConfig")
class DataQualityGateConfigSerializer(serializers.Serializer):
    """The team-level materialization gate. Checks always run and warn; this only toggles blocking."""

    gate_materialization_on_checks = serializers.BooleanField(
        help_text="When true, a materialization whose error-severity checks fail is not published; "
        "the previous version keeps serving and downstream models are skipped."
    )


@extend_schema_serializer(component_name="DataQualityCheckType")
class CheckTypeSerializer(serializers.Serializer):
    """One entry of the check-type catalog, so an agent can author config without guessing."""

    check_type = serializers.CharField(help_text="Value to pass as check_type.")
    description = serializers.CharField(help_text="What the check asserts and what counts as a failure.")
    requires_column = serializers.BooleanField(help_text="Whether column_name must be set for this type.")
    config_schema = CheckConfigField(help_text="JSON schema the config object is validated against.")
