import ast
from datetime import UTC

from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.html import format_html

from posthog.models.data_deletion_request import (
    DataDeletionRequest,
    ExecutionMode,
    RequestStatus,
    RequestType,
    build_deletion_count_query,
    invalidate_compiled_predicate_cache,
)
from posthog.models.team import Team

CRITERIA_FIELDS = {
    "request_type",
    "events",
    "delete_all_events",
    "properties",
    "person_properties",
    "start_time",
    "end_time",
    "hogql_predicate",
    "hogql_query",
    "hogql_variables",
    "person_uuids",
    "person_distinct_ids",
    "person_drop_profiles",
    "person_drop_events",
    "person_drop_recordings",
}
CLICKHOUSE_TEAM_GROUP = "ClickHouse Team"

PERSON_REMOVAL_FIELDS = (
    "person_uuids",
    "person_distinct_ids",
    "person_drop_profiles",
    "person_drop_events",
    "person_drop_recordings",
)

UNSUPPORTED_REQUEST_TYPES = (
    RequestType.HOGQL_EVENT_REMOVAL,
    RequestType.PERSON_REMOVAL,
    RequestType.PROPERTY_REMOVAL,
)

# Unsupported types that ClickHouse Team members may still pick on the create form.
CLICKHOUSE_TEAM_REQUEST_TYPES = (RequestType.PROPERTY_REMOVAL,)

# Requests can only be edited while draft or pending. Once approved (or later), the
# criteria are locked — operators must explicitly "revert to draft" to change them.
EDITABLE_STATUSES = {RequestStatus.DRAFT, RequestStatus.PENDING}

# The non-readonly fields rendered in the fieldsets. When a request is locked these are
# added to readonly_fields so the whole form becomes read-only.
EDITABLE_FIELDS = (
    "team_id",
    "request_type",
    "start_time",
    "end_time",
    "events",
    "delete_all_events",
    "properties",
    "person_properties",
    "hogql_predicate",
    "notes",
)

# Dagster Cloud deployment slug per PostHog cloud environment. The admin runs on web pods, which
# don't carry DAGSTER_DOMAIN (only Dagster pods do), so the run URL is derived from CLOUD_DEPLOYMENT.
DAGSTER_DEPLOYMENT_BY_CLOUD = {"US": "prod-us", "EU": "prod-eu", "DEV": "dev"}


def dagster_run_url(run_id: str) -> str | None:
    """Link to a Dagster run, or None when the deployment can't be identified (local/self-hosted)."""
    if settings.DAGSTER_DOMAIN:
        return f"https://{settings.DAGSTER_DOMAIN}/runs/{run_id}"
    deployment = DAGSTER_DEPLOYMENT_BY_CLOUD.get((settings.CLOUD_DEPLOYMENT or "").upper())
    if deployment:
        return f"https://posthog.dagster.cloud/{deployment}/runs/{run_id}"
    return None


# ---------------------------------------------------------------------------
# Custom widget + field for ArrayField editing
# ---------------------------------------------------------------------------

# The widget renders markup only. Its behaviour lives in a nonce'd block in
# admin/posthog/datadeletionrequest/change_form.html, because a widget's render() receives no
# request and so cannot reach {{ request.csp_nonce }}. Admin pages serve a policy whose script-src
# carries no 'unsafe-inline', so an un-nonced inline script here is refused and the preview never
# runs. Keeping the script in the template also emits it once rather than once per field.
_WIDGET_TEMPLATE = '{html}<div class="array-textarea-preview" data-textarea-id="{id}" style="margin-top:6px"></div>'


class ArrayTextareaWidget(forms.Textarea):
    """Textarea that displays list values one-per-line and shows a live parsed preview."""

    def __init__(self, attrs=None):
        defaults = {"rows": 5, "style": "font-family: monospace; width: 100%;"}
        if attrs:
            defaults.update(attrs)
        super().__init__(attrs=defaults)

    def format_value(self, value):
        if isinstance(value, list):
            return "\n".join(str(v) for v in value)
        return value

    def render(self, name, value, attrs=None, renderer=None):
        html = super().render(name, value, attrs, renderer)
        widget_id = attrs.get("id", f"id_{name}") if attrs else f"id_{name}"
        # html from super() is already a SafeString; widget_id is Django-generated (e.g. "id_events"),
        # not user input — format_html still HTML-escapes it for defense in depth.
        return format_html(_WIDGET_TEMPLATE, html=html, id=widget_id)


class ArrayTextareaField(forms.CharField):
    """Form field that parses newline-separated or JSON array input into a list."""

    widget = ArrayTextareaWidget

    def clean(self, value):
        value = super().clean(value)
        if not value:
            return []
        text = value.strip()
        if text.startswith("["):
            # ast.literal_eval accepts both Python-style ('a') and JSON-style ("a") quotes
            try:
                parsed = ast.literal_eval(text)
                if isinstance(parsed, list | tuple):
                    return [str(item).strip() for item in parsed if str(item).strip()]
            except (ValueError, SyntaxError):
                pass
        return [line.strip() for line in text.split("\n") if line.strip()]


class DataDeletionRequestForm(forms.ModelForm):
    events = ArrayTextareaField(
        required=False,
        help_text="One event name per line. You can also paste a JSON array. "
        "Leave empty only when 'delete all events' is set.",
    )
    properties = ArrayTextareaField(
        required=False,
        help_text="One property name per line. You can also paste a JSON array. Required for property removal requests when person_properties is empty.",
    )
    person_properties = ArrayTextareaField(
        required=False,
        help_text="One property name per line. You can also paste a JSON array. "
        "Properties to remove from events.person_properties. Required for property removal requests when properties is empty.",
    )
    hogql_predicate = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 4, "style": "font-family: monospace; width: 100%;"}),
        help_text="Optional HogQL boolean expression (validated against the events table). "
        "Combined with the other filters via AND. Example: properties.$browser = 'Chrome'.",
    )

    # DataDeletionRequestAdmin.get_form sets this for ClickHouse Team members.
    offer_clickhouse_team_types: bool = False

    class Meta:
        model = DataDeletionRequest
        exclude = PERSON_REMOVAL_FIELDS

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request_type = self.fields.get("request_type")
        if isinstance(request_type, forms.ChoiceField):
            current_type = getattr(self.instance, "request_type", None)
            hidden_types = set(UNSUPPORTED_REQUEST_TYPES)
            if self.offer_clickhouse_team_types:
                hidden_types -= set(CLICKHOUSE_TEAM_REQUEST_TYPES)
            request_type.choices = [
                (value, label)
                for value, label in RequestType.choices
                if value not in hidden_types or value == current_type
            ]


@admin.register(DataDeletionRequest)
class DataDeletionRequestAdmin(admin.ModelAdmin):
    form = DataDeletionRequestForm
    actions = ["duplicate_requests"]
    list_display = (
        "id",
        "team_id",
        "request_type",
        "status",
        "events",
        "start_time",
        "end_time",
        "created_by",
        "approved",
        "attempt_count",
        "last_executed_at",
        "created_at",
    )
    list_filter = ("request_type", "status", "requires_approval", "approved", "approved_automatically")
    search_fields = ("team_id", "events", "properties", "person_properties", "notes")
    readonly_fields = (
        "team_details",
        "status",
        "count",
        "part_count",
        "parts_size",
        "parts_row_count",
        "min_timestamp",
        "max_timestamp",
        "stats_calculated_at",
        "hogql_query",
        "hogql_variables",
        "created_at",
        "created_by",
        "updated_at",
        "criteria_updated_by",
        "criteria_updated_at",
        "approved",
        "approved_automatically",
        "approved_by",
        "approved_at",
        "execution_mode",
        "attempt_count",
        "first_executed_at",
        "last_executed_at",
        "last_dagster_run",
        "rendered_count_query",
    )
    ordering = ("-created_at",)
    change_form_template = "admin/posthog/datadeletionrequest/change_form.html"

    fieldsets = (
        (
            None,
            {
                "fields": (
                    "team_id",
                    "request_type",
                    "status",
                    "start_time",
                    "end_time",
                    "events",
                    "delete_all_events",
                    "properties",
                    "person_properties",
                    "hogql_predicate",
                    "hogql_query",
                    "hogql_variables",
                    "notes",
                ),
            },
        ),
        (
            "ClickHouse stats",
            {
                "fields": (
                    "count",
                    "part_count",
                    "parts_size",
                    "parts_row_count",
                    "min_timestamp",
                    "max_timestamp",
                    "stats_calculated_at",
                    "rendered_count_query",
                ),
                "description": "Populated by executing a ClickHouse query. Not editable.",
            },
        ),
        (
            "Audit trail",
            {
                "fields": (
                    "created_by",
                    "created_at",
                    "criteria_updated_by",
                    "criteria_updated_at",
                    "updated_at",
                    "approved",
                    "approved_automatically",
                    "approved_by",
                    "approved_at",
                    "execution_mode",
                    "attempt_count",
                    "first_executed_at",
                    "last_executed_at",
                    "last_dagster_run",
                ),
            },
        ),
    )

    @admin.action(permissions=["add"], description="Duplicate selected requests (as new drafts)")
    def duplicate_requests(self, request, queryset):
        """Copy each selected request into a fresh draft, noting it's a copy of the original."""
        created = 0
        for original in queryset:
            original_url = request.build_absolute_uri(
                reverse("admin:posthog_datadeletionrequest_change", args=[original.pk])
            )
            copy_note = f"Copy of data deletion request {original.pk} ({original_url})."
            notes = f"{copy_note}\n\n{original.notes}" if original.notes else copy_note
            # Build a fresh draft from CRITERIA_FIELDS (the single source of truth) so a new
            # criteria field is copied automatically. Everything operational — stats, approval,
            # execution tracking — falls back to model defaults (DRAFT, no stats, not approved).
            criteria = {field: getattr(original, field) for field in CRITERIA_FIELDS}
            # Shallow-copy mutable list fields so the duplicate never aliases the original's lists.
            criteria = {k: list(v) if isinstance(v, list) else v for k, v in criteria.items()}
            if original.request_type == RequestType.HOGQL_EVENT_REMOVAL:
                criteria["execution_mode"] = ExecutionMode.DEFERRED
            DataDeletionRequest.objects.create(
                **criteria,
                team_id=original.team_id,
                requires_approval=original.requires_approval,
                notes=notes,
                status=RequestStatus.DRAFT,
                created_by=request.user,
                created_by_staff=request.user.is_staff,
            )
            created += 1
        messages.success(request, f"Duplicated {created} request(s) as new draft(s).")

    @admin.display(description="Team")
    def team_details(self, obj: DataDeletionRequest) -> str:
        team = Team.objects.select_related("organization").filter(id=obj.team_id).first()
        if team is None:
            return format_html("{} <em>(team not found)</em>", obj.team_id)
        return format_html(
            '<a href="{}">{}</a> {} · organization <a href="{}">{}</a> {}',
            reverse("admin:posthog_team_change", args=[team.pk]),
            team.pk,
            team.name,
            reverse("admin:posthog_organization_change", args=[team.organization_id]),
            team.organization_id,
            team.organization.name,
        )

    def get_fieldsets(self, request, obj=None):
        fieldsets = super().get_fieldsets(request, obj)
        if obj is None:
            return fieldsets
        return [
            (name, {**options, "fields": tuple("team_details" if f == "team_id" else f for f in options["fields"])})
            for name, options in fieldsets
        ]

    @admin.display(description="Last Dagster run")
    def last_dagster_run(self, obj: DataDeletionRequest) -> str:
        """Link to the Dagster run of the latest execution attempt, for debugging in-flight requests."""
        if not obj.last_dagster_run_id:
            return "—"
        url = dagster_run_url(obj.last_dagster_run_id)
        if url is None:
            return obj.last_dagster_run_id
        return format_html('<a href="{}" target="_blank" rel="noopener">{}</a>', url, obj.last_dagster_run_id)

    @admin.display(description="Count query (ready to paste)")
    def rendered_count_query(self, obj: DataDeletionRequest) -> str:
        """Show the fully-substituted ClickHouse COUNT query operators can copy/paste."""
        from posthog.clickhouse.client.escape import substitute_params_for_display

        if obj.pk is None or not obj.team_id or not obj.start_time or not obj.end_time:
            return "—"
        try:
            template, params = build_deletion_count_query(obj)
            rendered = substitute_params_for_display(template, params)
        except Exception as exc:
            return format_html("<em>Could not render query: {}</em>", str(exc))
        return format_html(
            '<pre style="white-space: pre-wrap; background: #f5f5f5; padding: 8px;">{}</pre>',
            rendered,
        )

    def _is_locked(self, obj: DataDeletionRequest | None) -> bool:
        """Approved and later requests are locked — only draft/pending are editable."""
        return obj is not None and obj.pk is not None and obj.status not in EDITABLE_STATUSES

    def get_readonly_fields(self, request, obj=None):
        readonly = super().get_readonly_fields(request, obj)
        if self._is_locked(obj):
            return tuple(readonly) + EDITABLE_FIELDS
        if obj is not None:
            # team_id is immutable once the request exists — a request belongs to one team.
            return (*tuple(readonly), "team_id")
        return readonly

    def get_form(self, request, obj=None, change=False, **kwargs):
        form = super().get_form(request, obj, change=change, **kwargs)
        is_clickhouse_team = request.user.groups.filter(name=CLICKHOUSE_TEAM_GROUP).exists()
        return type(form.__name__, (form,), {"offer_clickhouse_team_types": is_clickhouse_team})

    def get_changeform_initial_data(self, request):
        initial: dict[str, object] = dict(super().get_changeform_initial_data(request))
        # The split datetime widget can't render a raw query-string value, so a prefilled add link
        # with dates would error. Parse them, read naive values as UTC, and drop what doesn't parse.
        for field in ("start_time", "end_time"):
            value = initial.get(field)
            if not isinstance(value, str):
                continue
            try:
                parsed = parse_datetime(value)
            except ValueError:
                parsed = None
            if parsed is None:
                initial.pop(field)
            elif timezone.is_naive(parsed):
                initial[field] = timezone.make_aware(parsed, UTC)
            else:
                initial[field] = parsed
        return initial

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
            obj.created_by_staff = request.user.is_staff
        elif form.changed_data and CRITERIA_FIELDS & set(form.changed_data):
            obj.criteria_updated_by = request.user
            obj.criteria_updated_at = timezone.now()
            # Criteria changed — the cached compiled predicate (used by stats/preview) is stale.
            invalidate_compiled_predicate_cache(obj.pk)
            obj.count = None
            obj.part_count = None
            obj.parts_size = None
            obj.parts_row_count = None
            obj.min_timestamp = None
            obj.max_timestamp = None
            obj.stats_calculated_at = None
            # Rows cleaned under the old criteria are ordinary candidates for the new ones —
            # a stale marker would make the copy pass skip them as "already cleaned".
            obj.property_removal_marker = None
            if obj.status != RequestStatus.DRAFT:
                obj.status = RequestStatus.DRAFT
                messages.warning(request, "Deletion criteria were changed — status has been reset to draft.")
        if obj.request_type == RequestType.EVENT_REMOVAL and (obj.properties or obj.person_properties):
            obj.properties = []
            obj.person_properties = []
            messages.info(request, "Properties cleared — event removal requests do not use properties.")
        if obj.request_type == RequestType.PERSON_REMOVAL and (
            obj.events or obj.delete_all_events or obj.hogql_predicate
        ):
            obj.events = []
            obj.delete_all_events = False
            obj.hogql_predicate = ""
            messages.info(
                request,
                "Event filters cleared — person removal requests do not use events/hogql_predicate.",
            )
        if obj.request_type != RequestType.PERSON_REMOVAL and (
            obj.person_uuids
            or obj.person_distinct_ids
            or obj.person_drop_profiles
            or obj.person_drop_events
            or obj.person_drop_recordings
        ):
            obj.person_uuids = []
            obj.person_distinct_ids = []
            obj.person_drop_profiles = None
            obj.person_drop_events = None
            obj.person_drop_recordings = None
            messages.info(request, "Person targets cleared — only person_removal requests use them.")
        super().save_model(request, obj, form, change)

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        obj = self.get_object(request, object_id)
        if obj:
            if obj.request_type == RequestType.PROPERTY_REMOVAL and not obj.properties and not obj.person_properties:
                messages.warning(
                    request, "This is a property removal request but no properties or person_properties are specified."
                )
            if obj.request_type == RequestType.PERSON_REMOVAL:
                if not (obj.person_uuids or obj.person_distinct_ids):
                    messages.warning(request, "This is a person removal request but no person targets are specified.")
                elif not (obj.person_drop_profiles or obj.person_drop_events or obj.person_drop_recordings):
                    messages.warning(
                        request,
                        "This person removal request has no drop flag set "
                        "(profiles/events/recordings) — nothing will be deleted.",
                    )
            if self._is_locked(obj):
                # Locked requests have no editable fields — hide the misleading Save row.
                extra_context["show_save"] = False
                extra_context["show_save_and_continue"] = False
                extra_context["show_save_and_add_another"] = False
        return super().change_view(request, object_id, form_url, extra_context)
