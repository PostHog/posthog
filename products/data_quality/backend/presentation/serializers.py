"""DRF serializers for data quality checks.

Source of truth for the generated frontend and MCP types, so every field carries help_text. The
per-type ``config`` shape is validated against the registry's JSON schema rather than modeled as a
union: a new check type must not need a serializer change.
"""

from typing import Any

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field, extend_schema_serializer
from rest_framework import serializers
from rest_framework.exceptions import ErrorDetail
from rest_framework.settings import api_settings

from posthog.api.shared import UserBasicSerializer

from ..facade import api
from ..facade.enums import CheckSeverity, CheckType, CreatedSource, ScheduleInterval, SubjectType
from ..facade.models import DataQualityCheck, DataQualityCheckRun, DataQualitySuiteRun


@extend_schema_field(OpenApiTypes.OBJECT)
class CheckConfigField(serializers.JSONField):
    """Type-specific configuration. Call /check_types/ for the JSON schema of each type."""


class DataQualityMetricSubjectSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Metric identifier used by the nested check endpoints.")
    name = serializers.CharField(help_text="Queryable metric name.")
    display_name = serializers.CharField(allow_blank=True, help_text="Metric label shown in the data catalog.")


@extend_schema_serializer(component_name="DataQualitySubjectRef")
class DataQualitySubjectRefSerializer(serializers.Serializer):
    """The subject a request names, wherever it names it: a body, a query string, or both."""

    subject_type = serializers.ChoiceField(
        choices=[(t.value, t.value) for t in SubjectType],
        help_text="Kind of object: 'table', 'view', 'metric', or 'posthog_table'.",
    )
    subject_uuid = serializers.UUIDField(help_text="Id of the table, view, metric, or PostHog table.")


@extend_schema_serializer(component_name="DataQualitySubject")
class DataQualitySubjectSerializer(serializers.Serializer):
    """One thing a check can be authored on, whatever kind it is."""

    subject_type = serializers.ChoiceField(
        choices=[(t.value, t.value) for t in SubjectType],
        help_text="Kind of object: 'table', 'view', 'metric', or 'posthog_table'. "
        "Pass it back as subject_type when creating a check.",
    )
    id = serializers.CharField(help_text="Id of the subject. Pass it back as subject_uuid when creating a check.")
    name = serializers.CharField(help_text="Queryable name of the subject.")
    display_name = serializers.CharField(
        allow_blank=True, help_text="Label shown in the data catalog. Blank for tables and views."
    )
    time_column = serializers.CharField(
        allow_blank=True,
        help_text="Column a lookback window bounds, or blank for a subject that has none.",
    )
    columns = serializers.DictField(
        child=serializers.CharField(),
        help_text="Column name to ClickHouse type. Empty for a metric, and for a view that has not run yet.",
    )
    editable = serializers.BooleanField(
        help_text="Whether the caller may author a check on this subject. A subject that is only readable "
        "can still be the target of a relationships check."
    )


class DataQualityOutputColumnSerializer(serializers.Serializer):
    name = serializers.CharField(help_text="Output column name available through the {metric} relation.")
    type = serializers.CharField(allow_null=True, help_text="ClickHouse type, or null when it could not be inferred.")


class DataQualityOutputSchemaSerializer(serializers.Serializer):
    columns = DataQualityOutputColumnSerializer(many=True, help_text="Columns returned by the saved metric query.")


@extend_schema_serializer(component_name="DataQualityCheck")
class DataQualityCheckSerializer(serializers.ModelSerializer):
    """A check as it reads back, and everything an edit may change about it.

    The subject is not one of those: it is writable only on ``DataQualityCheckCreate``.
    """

    subject_type = serializers.ChoiceField(
        choices=[(t.value, t.value) for t in SubjectType],
        read_only=True,
        help_text="Kind of object being checked: 'table', 'view', 'metric', or 'posthog_table'.",
    )
    subject_uuid = serializers.UUIDField(
        read_only=True,
        allow_null=True,
        help_text="Id of the table, view, metric, or PostHog table being checked. Null once the subject is deleted.",
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
        help_text="When the check last passed. Read failing_since for how long a failing check has been failing. "
        "Null means it has not passed within the run retention window.",
    )
    failing_since = serializers.DateTimeField(
        read_only=True,
        allow_null=True,
        help_text="When the current streak of failing runs started, so a failing check can say how long "
        "it has been failing. Null when the check is not failing.",
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
            "failing_since",
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
            "failing_since",
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

    def validate(self, attrs: dict) -> dict:
        if self.instance is not None:
            return attrs

        try:
            api.validate_check(
                self.context["get_team"](),
                str(self.context.get("subject_type") or ""),
                str(self.context.get("subject_uuid") or ""),
                attrs.get("check_type") or "",
                attrs.get("column_name") or "",
                attrs.get("config") or {},
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
                authorize=self.context.get("authorize_check_edit"),
                **validated_data,
            )
        except (api.CheckConfigError, api.SubjectUnresolvableError, api.UnknownCheckTypeError) as err:
            raise serializers.ValidationError({"config": str(err)})
        except api.CheckEditConflict as conflict:
            # Rendered beside the offending fields rather than as a status code, so the editor can
            # keep the draft open and point at what to change.
            fields = conflict.fields or (api_settings.NON_FIELD_ERRORS_KEY,)
            raise serializers.ValidationError(
                {field: ErrorDetail(str(conflict), code=conflict.code) for field in fields}
            )


@extend_schema_serializer(component_name="DataQualityCheckCreate")
class DataQualityCheckCreateSerializer(DataQualityCheckSerializer):
    """The create body, where the subject is named for the only time in a check's life."""

    subject_type = serializers.ChoiceField(
        choices=[(t.value, t.value) for t in SubjectType],
        help_text="Kind of object to check: 'table', 'view', 'metric', or 'posthog_table'.",
    )
    subject_uuid = serializers.UUIDField(help_text="Id of the table, view, metric, or PostHog table to check.")


@extend_schema_serializer(component_name="DataQualityOverviewCheck")
class DataQualityOverviewCheckSerializer(DataQualityCheckSerializer):
    """A check plus where its subject can be opened, for the project-wide list.

    The per-subject surfaces already know their parent; only this one lists checks across every
    table and view, so only this one needs to say where each subject lives. The ids are resolved
    for a whole page at once and handed in through ``subject_locations`` in the context.
    """

    subject_node_id = serializers.SerializerMethodField(
        help_text="Data modeling node of the view or PostHog table this check audits, or null when it is on "
        "no DAG or the subject is a warehouse table."
    )
    subject_source_id = serializers.SerializerMethodField(
        help_text="Warehouse source of the table this check audits, or null when the subject is a view."
    )
    subject_schema_id = serializers.SerializerMethodField(
        help_text="Warehouse source schema of the table this check audits, or null when the subject is a view."
    )
    subject_metric_name = serializers.SerializerMethodField(
        help_text="Current metric name for opening its Tests tab, or null for other subjects."
    )

    class Meta(DataQualityCheckSerializer.Meta):
        fields = [
            *DataQualityCheckSerializer.Meta.fields,
            "subject_node_id",
            "subject_source_id",
            "subject_schema_id",
            "subject_metric_name",
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

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_subject_metric_name(self, obj: DataQualityCheck) -> str | None:
        return self._location(obj).metric_name


@extend_schema_serializer(component_name="DataQualityCheckScheduleUpdate")
class DataQualityCheckScheduleUpdateSerializer(DataQualitySubjectRefSerializer):
    """Which subject's schedule to change, and what to change about it."""

    SCHEDULE_FIELDS = ("interval", "enabled")

    interval = serializers.ChoiceField(
        choices=list(ScheduleInterval), required=False, help_text="How often all enabled checks on the subject run."
    )
    enabled = serializers.BooleanField(required=False, help_text="Whether checks run automatically on this schedule.")

    @property
    def schedule_changes(self) -> dict:
        return {key: value for key, value in self.validated_data.items() if key in self.SCHEDULE_FIELDS}


class DataQualityCheckScheduleSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True, help_text="Schedule identifier.")
    interval = serializers.ChoiceField(
        choices=list(ScheduleInterval), read_only=True, help_text="How often the checks run."
    )
    enabled = serializers.BooleanField(read_only=True, help_text="Whether the schedule runs automatically.")
    next_run_at = serializers.DateTimeField(
        read_only=True, allow_null=True, help_text="Next scheduled execution time, if enabled."
    )
    last_run_at = serializers.DateTimeField(
        read_only=True, allow_null=True, help_text="Most recent visible scheduled suite execution time."
    )
    last_suite_run = serializers.UUIDField(
        read_only=True, allow_null=True, help_text="Most recent visible scheduled suite."
    )


class DataQualitySubjectScheduleSerializer(DataQualityCheckScheduleSerializer):
    """One subject's schedule, in the project-wide listing."""

    subject_type = serializers.ChoiceField(
        choices=[(t.value, t.value) for t in SubjectType], read_only=True, help_text="'metric' or 'posthog_table'."
    )
    subject_uuid = serializers.UUIDField(read_only=True, help_text="Id of the metric or PostHog table.")

    def to_representation(self, instance: api.SubjectSchedule) -> dict[str, Any]:
        row = super().to_representation(instance.schedule)
        row["subject_type"] = str(instance.subject_type)
        row["subject_uuid"] = str(instance.subject_uuid)
        return row


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
    check_name = serializers.SerializerMethodField(
        help_text="Name the check carries now, so a run can be told from the others in its suite. "
        "Null when the check is unnamed, has been hard deleted, or is out of your reach today -- "
        "describe the run by check_type and column_name instead."
    )

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_check_name(self, obj: DataQualityCheckRun) -> str | None:
        # A surface that serves runs from several checks passes the ones it may not name; a surface
        # that already authorized the single check it serves passes nothing and names it.
        check = obj.quality_check
        if not check or check.id in self.context.get("unnamable_check_ids", frozenset()):
            return None
        return check.name or None

    class Meta:
        model = DataQualityCheckRun
        fields = [
            "id",
            "quality_check",
            "check_name",
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
    trigger = serializers.CharField(read_only=True, help_text="manual, materialization, source_sync, or scheduled.")
    subject_type = serializers.SerializerMethodField(
        help_text="'table', 'view', 'metric', or 'posthog_table' when the run targets exactly one subject, "
        "including a run of a single check on that subject; null for a run spanning several subjects."
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

    subject_type = serializers.CharField(help_text="'table', 'view', 'metric', or 'posthog_table'.")
    subject_uuid = serializers.CharField(help_text="Id of the table, view, metric, or PostHog table.")
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
    subject_type = serializers.ChoiceField(
        choices=[(t.value, t.value) for t in SubjectType],
        required=False,
        help_text="Narrow the run to one subject. Pass subject_uuid with it. Ignored when check_ids is given.",
    )
    subject_uuid = serializers.UUIDField(
        required=False,
        help_text="Id of the subject to run every enabled check on. Pass subject_type with it.",
    )

    def validate(self, attrs: dict) -> dict:
        if bool(attrs.get("subject_type")) != bool(attrs.get("subject_uuid")):
            raise serializers.ValidationError(
                {"subject_uuid": "Name the subject with both subject_type and subject_uuid, or neither."}
            )
        return attrs


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
