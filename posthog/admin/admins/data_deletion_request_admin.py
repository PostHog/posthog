import ast

from django import forms
from django.contrib import admin, messages
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.clickhouse.workload import Workload
from posthog.models.data_deletion_request import (
    DataDeletionRequest,
    ExecutionMode,
    RequestStatus,
    RequestType,
    compile_hogql_predicate,
    event_match_params,
    event_match_sql_fragment,
    jsonhas_expr,
)

CRITERIA_FIELDS = {
    "request_type",
    "events",
    "delete_all_events",
    "properties",
    "start_time",
    "end_time",
    "hogql_predicate",
    "person_uuids",
    "person_distinct_ids",
    "person_drop_profiles",
    "person_drop_events",
    "person_drop_recordings",
}
CLICKHOUSE_TEAM_GROUP = "ClickHouse Team"


# ---------------------------------------------------------------------------
# Custom widget + field for ArrayField editing
# ---------------------------------------------------------------------------

# JS template for the live preview/normalizer. All literal `{`/`}` are doubled because
# we render via format_html(), which uses str.format() semantics. `{id}` is the only
# substitution slot and gets the widget element id.
_WIDGET_TEMPLATE = """{html}<div id="{id}_preview" style="margin-top:6px"></div>
<script>
(function() {{
    var ta = document.getElementById('{id}');
    if (!ta) return;
    var preview = document.getElementById('{id}_preview');

    function parse(text) {{
        text = text.trim();
        if (!text) return [];
        if (text.startsWith('[')) {{
            // Try JSON as-is, then with single→double quote swap (Python-style arrays).
            // Safe here because event/property names don't contain single quotes.
            var candidates = [text, text.replace(/'/g, '"')];
            for (var i = 0; i < candidates.length; i++) {{
                try {{
                    var arr = JSON.parse(candidates[i]);
                    if (Array.isArray(arr)) {{
                        return arr.map(function(s){{return String(s).trim()}}).filter(Boolean);
                    }}
                }} catch(e) {{}}
            }}
        }}
        return text.split('\\n').map(function(s){{return s.trim()}}).filter(Boolean);
    }}

    function render() {{
        var items = parse(ta.value);
        if (items.length === 0) {{
            preview.innerHTML = '<em style="color:#999">No items</em>';
            return;
        }}
        preview.innerHTML = '<strong>' + items.length + ' item(s):</strong> ' +
            items.map(function(s){{return '<code style="background:#e8e8e8;padding:2px 6px;border-radius:3px;margin:2px">' + s.replace(/</g,'&lt;') + '</code>'}}).join(' ');
    }}

    function normalizeIfArray() {{
        // If the current text is an array literal, rewrite it to one-per-line.
        // Only called on paste/blur to avoid clobbering live editing.
        var text = ta.value.trim();
        if (!text.startsWith('[')) return;
        var items = parse(text);
        if (items.length > 0) {{
            ta.value = items.join('\\n');
            render();
        }}
    }}

    ta.addEventListener('input', render);
    ta.addEventListener('blur', normalizeIfArray);
    ta.addEventListener('paste', function() {{ setTimeout(normalizeIfArray, 0); }});
    render();
}})();
</script>
"""


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
        help_text="One property name per line. You can also paste a JSON array. Required for property removal requests.",
    )
    hogql_predicate = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 4, "style": "font-family: monospace; width: 100%;"}),
        help_text="Optional HogQL boolean expression (validated against the events table). "
        "Combined with the other filters via AND. Example: properties.$browser = 'Chrome'.",
    )
    person_uuids = ArrayTextareaField(
        required=False,
        help_text="One person UUID per line. You can also paste a JSON array. "
        "Combined with person_distinct_ids; total ≤ 1000.",
    )
    person_distinct_ids = ArrayTextareaField(
        required=False,
        help_text="One person distinct ID per line. You can also paste a JSON array. "
        "Combined with person_uuids; total ≤ 1000.",
    )

    class Meta:
        model = DataDeletionRequest
        fields = "__all__"


def _append_hogql_predicate(fragment: str, params: dict, obj, *, target_data_table: bool) -> tuple[str, dict]:
    """Append the compiled HogQL predicate (if any) to ``fragment`` and merge params."""
    hogql_sql, hogql_values = compile_hogql_predicate(obj, target_data_table=target_data_table)
    if not hogql_sql:
        return fragment, params
    combined = f"{fragment} AND ({hogql_sql})".strip() if fragment else f"AND ({hogql_sql})"
    params.update(hogql_values)
    return combined, params


def _build_event_filter(obj, *, target_data_table: bool = False) -> tuple[str, dict]:
    """Build the WHERE clause and params for matching events."""
    return _append_hogql_predicate(
        event_match_sql_fragment(obj), event_match_params(obj), obj, target_data_table=target_data_table
    )


def _build_property_filter(obj, *, target_data_table: bool = False) -> tuple[str, dict]:
    """Build the WHERE clause addition and params for matching properties."""
    event_clause = event_match_sql_fragment(obj)
    params: dict = event_match_params(obj)
    properties = obj.properties
    if len(properties) == 1:
        property_clause = f"AND {jsonhas_expr(properties[0], 'fp_0')}"
    else:
        exprs = [jsonhas_expr(prop, f"fp_{i}") for i, prop in enumerate(properties)]
        property_clause = f"AND ({' OR '.join(exprs)})"

    for i, prop in enumerate(properties):
        for j, part in enumerate(prop.split(".")):
            params[f"fp_{i}_{j}"] = part

    filter_clause = f"{event_clause} {property_clause}".strip()
    return _append_hogql_predicate(filter_clause, params, obj, target_data_table=target_data_table)


def _event_count_query_template(extra_filter: str) -> str:
    # Counts run against the distributed ``events`` table so operators get a
    # cluster-wide number; the actual deletions still target ``sharded_events``.
    # nosemgrep: clickhouse-fstring-param-audit (extra_filter is built from internal helpers, not user input)
    return f"""
            SELECT
                count() AS events,
                count(DISTINCT _part) AS parts,
                min(timestamp) AS min_ts,
                max(timestamp) AS max_ts
            FROM events
            WHERE team_id = %(team_id)s
              AND timestamp >= %(start_time)s
              AND timestamp < %(end_time)s
              {extra_filter}
            """


def build_deletion_count_query(obj: DataDeletionRequest) -> tuple[str, dict]:
    """Return the (SQL template, params) used to count rows matching this request.

    Mirrors ``_fetch_stats`` so admin users can copy the query and run it
    independently — ``substitute_params_for_display`` is the companion renderer.
    """
    if obj.request_type == RequestType.PROPERTY_REMOVAL:
        extra_filter, params = _build_property_filter(obj)
    else:
        extra_filter, params = _build_event_filter(obj)
    return _event_count_query_template(extra_filter), params


def _fetch_stats(
    team_id: int,
    events_filter: str,
    events_params: dict,
    sharded_filter: str,
    sharded_params: dict,
) -> dict:
    """Run event count + parts size queries against ClickHouse.

    The two filters share the same ``hogql_val_*`` keys but are qualified for
    their respective tables (``events`` vs ``sharded_events``), so any
    materialized-column references resolve correctly in each query.
    """
    from posthog.clickhouse.client import sync_execute

    with tags_context(
        product=Product.INTERNAL,
        feature=Feature.DATA_DELETION,
        team_id=team_id,
        workload=Workload.OFFLINE,
        query_type="delete_event_count",
    ):
        event_result = sync_execute(
            _event_count_query_template(events_filter),
            events_params,
            team_id=team_id,
            readonly=True,
            workload=Workload.OFFLINE,
            ch_user=ClickHouseUser.META,
        )

    with tags_context(
        product=Product.INTERNAL,
        feature=Feature.DATA_DELETION,
        team_id=team_id,
        workload=Workload.OFFLINE,
        query_type="delete_part_count",
    ):
        from django.conf import settings as django_settings

        cluster = django_settings.CLICKHOUSE_CLUSTER

        # nosemgrep: clickhouse-fstring-param-audit (filter built from internal helpers; cluster from Django settings)
        parts_result = sync_execute(
            f"""
            SELECT
                count() AS part_count,
                sum(p.bytes_on_disk) AS total_size_on_disk,
                sum(p.rows) AS total_rows_in_those_parts
            FROM cluster('{cluster}', system, parts) AS p
            INNER JOIN (
                SELECT DISTINCT _part AS name
                FROM sharded_events
                WHERE team_id = %(team_id)s
                  AND timestamp >= %(start_time)s
                  AND timestamp < %(end_time)s
                  {sharded_filter}
            ) AS matched ON p.name = matched.name
            WHERE p.table = 'sharded_events'
              AND p.active
            """,
            sharded_params,
            team_id=team_id,
            readonly=True,
            workload=Workload.OFFLINE,
            ch_user=ClickHouseUser.META,
        )

    return {
        "count": event_result[0][0] if event_result else 0,
        "min_timestamp": event_result[0][2] if event_result and event_result[0][0] else None,
        "max_timestamp": event_result[0][3] if event_result and event_result[0][0] else None,
        "part_count": parts_result[0][0] if parts_result else 0,
        "parts_size": parts_result[0][1] if parts_result else 0,
        "parts_row_count": parts_result[0][2] if parts_result else 0,
    }


def fetch_event_deletion_stats(obj: DataDeletionRequest):
    """Count events and affected parts for an event removal request."""
    events_filter, events_params = _build_event_filter(obj)
    sharded_filter, sharded_params = _build_event_filter(obj, target_data_table=True)
    return _fetch_stats(obj.team_id, events_filter, events_params, sharded_filter, sharded_params)


def fetch_property_deletion_stats(obj: DataDeletionRequest):
    """Count events with matching properties and affected parts for a property removal request."""
    if not obj.properties:
        raise ValueError("Cannot fetch stats for a property removal request with no properties specified.")
    events_filter, events_params = _build_property_filter(obj)
    sharded_filter, sharded_params = _build_property_filter(obj, target_data_table=True)
    return _fetch_stats(obj.team_id, events_filter, events_params, sharded_filter, sharded_params)


def fetch_deletion_stats(obj: DataDeletionRequest):
    """Dispatch to the appropriate stats function based on request type."""
    if obj.request_type == RequestType.PROPERTY_REMOVAL:
        return fetch_property_deletion_stats(obj)
    return fetch_event_deletion_stats(obj)


class DataDeletionRequestAdmin(admin.ModelAdmin):
    form = DataDeletionRequestForm
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
        "created_at",
    )
    list_filter = ("request_type", "status", "requires_approval", "approved")
    search_fields = ("team_id", "events", "properties", "notes")
    readonly_fields = (
        "status",
        "count",
        "part_count",
        "parts_size",
        "parts_row_count",
        "min_timestamp",
        "max_timestamp",
        "stats_calculated_at",
        "created_at",
        "created_by",
        "updated_at",
        "criteria_updated_by",
        "criteria_updated_at",
        "approved",
        "approved_by",
        "approved_at",
        "execution_mode",
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
                    "hogql_predicate",
                    "notes",
                    "requires_approval",
                ),
            },
        ),
        (
            "Person targets",
            {
                "fields": (
                    "person_uuids",
                    "person_distinct_ids",
                    "person_drop_profiles",
                    "person_drop_events",
                    "person_drop_recordings",
                ),
                "classes": ("data-deletion-person-fields",),
                "description": "Only used for person_removal requests.",
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
                    "approved_by",
                    "approved_at",
                    "execution_mode",
                ),
            },
        ),
    )

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

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
            obj.created_by_staff = request.user.is_staff
        elif form.changed_data and CRITERIA_FIELDS & set(form.changed_data):
            obj.criteria_updated_by = request.user
            obj.criteria_updated_at = timezone.now()
            obj.count = None
            obj.part_count = None
            obj.parts_size = None
            obj.parts_row_count = None
            obj.min_timestamp = None
            obj.max_timestamp = None
            obj.stats_calculated_at = None
            if obj.status != RequestStatus.DRAFT:
                obj.status = RequestStatus.DRAFT
                messages.warning(request, "Deletion criteria were changed — status has been reset to draft.")
        if obj.request_type == RequestType.EVENT_REMOVAL and obj.properties:
            obj.properties = []
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
            if obj.request_type == RequestType.PROPERTY_REMOVAL and not obj.properties:
                messages.warning(request, "This is a property removal request but no properties are specified.")
            if obj.request_type == RequestType.PERSON_REMOVAL:
                if not (obj.person_uuids or obj.person_distinct_ids):
                    messages.warning(request, "This is a person removal request but no person targets are specified.")
                elif not (obj.person_drop_profiles or obj.person_drop_events or obj.person_drop_recordings):
                    messages.warning(
                        request,
                        "This person removal request has no drop flag set "
                        "(profiles/events/recordings) — nothing will be deleted.",
                    )
            extra_context["is_draft"] = obj.status == RequestStatus.DRAFT
            extra_context["submit_url"] = reverse("admin:posthog_datadeletionrequest_submit", args=[obj.pk])
            extra_context["can_approve"] = (
                obj.status == RequestStatus.PENDING and request.user.groups.filter(name=CLICKHOUSE_TEAM_GROUP).exists()
            )
            extra_context["approve_url"] = reverse("admin:posthog_datadeletionrequest_approve", args=[obj.pk])
            extra_context["can_revert_to_draft"] = obj.status in (RequestStatus.PENDING, RequestStatus.APPROVED)
            extra_context["revert_to_draft_url"] = reverse(
                "admin:posthog_datadeletionrequest_revert_to_draft", args=[obj.pk]
            )
        return super().change_view(request, object_id, form_url, extra_context)

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<path:object_id>/submit/",
                self.admin_site.admin_view(self.submit_view),
                name="posthog_datadeletionrequest_submit",
            ),
            path(
                "<path:object_id>/fetch-stats/",
                self.admin_site.admin_view(self.fetch_stats_view),
                name="posthog_datadeletionrequest_fetch_stats",
            ),
            path(
                "<path:object_id>/approve/",
                self.admin_site.admin_view(self.approve_view),
                name="posthog_datadeletionrequest_approve",
            ),
            path(
                "<path:object_id>/revert-to-draft/",
                self.admin_site.admin_view(self.revert_to_draft_view),
                name="posthog_datadeletionrequest_revert_to_draft",
            ),
        ]
        return custom_urls + urls

    def submit_view(self, request, object_id):
        obj = self.get_object(request, object_id)
        if not obj:
            return HttpResponseRedirect(reverse("admin:posthog_datadeletionrequest_changelist"))

        if obj.status != RequestStatus.DRAFT:
            messages.error(request, "Only draft requests can be submitted.")
            return HttpResponseRedirect(reverse("admin:posthog_datadeletionrequest_change", args=[obj.pk]))

        missing_properties = obj.request_type == RequestType.PROPERTY_REMOVAL and not obj.properties
        missing_person_selectors = obj.request_type == RequestType.PERSON_REMOVAL and not (
            obj.person_uuids or obj.person_distinct_ids
        )
        missing_person_drop_flag = obj.request_type == RequestType.PERSON_REMOVAL and not (
            obj.person_drop_profiles or obj.person_drop_events or obj.person_drop_recordings
        )
        can_submit = not (missing_properties or missing_person_selectors or missing_person_drop_flag)

        if request.method == "POST":
            if missing_properties:
                messages.error(request, "Cannot submit: property removal request requires at least one property.")
                return HttpResponseRedirect(reverse("admin:posthog_datadeletionrequest_change", args=[obj.pk]))
            if missing_person_selectors:
                messages.error(
                    request,
                    "Cannot submit: person removal request requires at least one person UUID or distinct ID.",
                )
                return HttpResponseRedirect(reverse("admin:posthog_datadeletionrequest_change", args=[obj.pk]))
            if missing_person_drop_flag:
                messages.error(
                    request,
                    "Cannot submit: person removal request requires at least one drop flag (profiles/events/recordings).",
                )
                return HttpResponseRedirect(reverse("admin:posthog_datadeletionrequest_change", args=[obj.pk]))
            updated = DataDeletionRequest.objects.filter(
                pk=obj.pk,
                status=RequestStatus.DRAFT,
            ).update(
                status=RequestStatus.PENDING,
                updated_at=timezone.now(),
            )
            if not updated:
                messages.error(request, "Request is no longer in draft status.")
                return HttpResponseRedirect(reverse("admin:posthog_datadeletionrequest_change", args=[obj.pk]))
            obj.refresh_from_db()
            self.log_change(request, obj, "Submitted: status changed from draft to pending.")
            messages.success(request, "Request submitted and is now pending.")
            return HttpResponseRedirect(reverse("admin:posthog_datadeletionrequest_change", args=[obj.pk]))

        context = {
            **self.admin_site.each_context(request),
            "obj": obj,
            "missing_properties": missing_properties,
            "missing_person_selectors": missing_person_selectors,
            "missing_person_drop_flag": missing_person_drop_flag,
            "is_person_removal": obj.request_type == RequestType.PERSON_REMOVAL,
            "can_submit": can_submit,
            "fetch_stats_url": reverse("admin:posthog_datadeletionrequest_fetch_stats", args=[obj.pk]),
            "opts": self.model._meta,
            "title": f"Submit deletion request {obj.pk}",
        }
        return TemplateResponse(request, "admin/posthog/datadeletionrequest/submit.html", context)

    def fetch_stats_view(self, request, object_id):
        obj = self.get_object(request, object_id)
        if not obj:
            return HttpResponseRedirect(reverse("admin:posthog_datadeletionrequest_changelist"))

        if request.method != "POST":
            return HttpResponseRedirect(reverse("admin:posthog_datadeletionrequest_submit", args=[obj.pk]))

        if obj.request_type == RequestType.PERSON_REMOVAL:
            # No ClickHouse query yet for person_removal — just count selectors.
            obj.count = len(obj.person_uuids) + len(obj.person_distinct_ids)
            obj.stats_calculated_at = timezone.now()
            obj.save(update_fields=["count", "stats_calculated_at", "updated_at"])
            self.log_change(request, obj, "Counted person_removal selectors.")
            messages.success(request, f"Selector count: {obj.count} person target(s).")
            return HttpResponseRedirect(reverse("admin:posthog_datadeletionrequest_submit", args=[obj.pk]))

        try:
            stats = fetch_deletion_stats(obj)
            obj.count = stats["count"]
            obj.part_count = stats["part_count"]
            obj.parts_size = stats["parts_size"]
            obj.parts_row_count = stats["parts_row_count"]
            obj.min_timestamp = stats["min_timestamp"]
            obj.max_timestamp = stats["max_timestamp"]
            obj.stats_calculated_at = timezone.now()
            obj.save(
                update_fields=[
                    "count",
                    "part_count",
                    "parts_size",
                    "parts_row_count",
                    "min_timestamp",
                    "max_timestamp",
                    "stats_calculated_at",
                    "updated_at",
                ]
            )
            self.log_change(request, obj, "Fetched ClickHouse stats.")
            messages.success(request, f"Stats fetched: {stats['count']:,} matching events found.")
        except Exception as e:
            messages.error(request, f"Failed to fetch stats: {e}")

        return HttpResponseRedirect(reverse("admin:posthog_datadeletionrequest_submit", args=[obj.pk]))

    def approve_view(self, request, object_id):
        obj = self.get_object(request, object_id)
        if not obj:
            return HttpResponseRedirect(reverse("admin:posthog_datadeletionrequest_changelist"))

        if not request.user.groups.filter(name=CLICKHOUSE_TEAM_GROUP).exists():
            messages.error(request, "Only ClickHouse Team members can approve deletion requests.")
            return HttpResponseRedirect(reverse("admin:posthog_datadeletionrequest_change", args=[obj.pk]))

        supports_deferred = obj.request_type == RequestType.EVENT_REMOVAL

        if request.method == "POST":
            execution_mode = request.POST.get("execution_mode", ExecutionMode.IMMEDIATE)
            if obj.request_type == RequestType.PERSON_REMOVAL:
                # person_removal is always IMMEDIATE — ignore any submitted value.
                execution_mode = ExecutionMode.IMMEDIATE
            if execution_mode not in ExecutionMode.values:
                messages.error(request, f"Invalid execution mode: {execution_mode!r}.")
                return HttpResponseRedirect(reverse("admin:posthog_datadeletionrequest_approve", args=[obj.pk]))
            if execution_mode == ExecutionMode.DEFERRED and not supports_deferred:
                messages.error(request, "Deferred execution is only supported for event removal requests.")
                return HttpResponseRedirect(reverse("admin:posthog_datadeletionrequest_approve", args=[obj.pk]))

            updated = DataDeletionRequest.objects.filter(
                pk=obj.pk,
                status=RequestStatus.PENDING,
            ).update(
                status=RequestStatus.APPROVED,
                approved=True,
                approved_by=request.user,
                approved_at=timezone.now(),
                execution_mode=execution_mode,
                updated_at=timezone.now(),
            )

            if not updated:
                messages.error(request, "Only pending requests can be approved.")
                return HttpResponseRedirect(reverse("admin:posthog_datadeletionrequest_change", args=[obj.pk]))

            obj.refresh_from_db()
            self.log_change(request, obj, f"Approved deletion request (execution_mode={execution_mode}).")
            messages.success(request, f"Deletion request approved ({obj.get_execution_mode_display()}).")
            return HttpResponseRedirect(reverse("admin:posthog_datadeletionrequest_change", args=[obj.pk]))

        if obj.status != RequestStatus.PENDING:
            messages.error(request, "Only pending requests can be approved.")
            return HttpResponseRedirect(reverse("admin:posthog_datadeletionrequest_change", args=[obj.pk]))

        context = {
            **self.admin_site.each_context(request),
            "obj": obj,
            "supports_deferred": supports_deferred,
            "is_person_removal": obj.request_type == RequestType.PERSON_REMOVAL,
            "execution_mode_choices": ExecutionMode.choices,
            "default_execution_mode": ExecutionMode.IMMEDIATE,
            "opts": self.model._meta,
            "title": f"Approve deletion request {obj.pk}",
        }
        return TemplateResponse(request, "admin/posthog/datadeletionrequest/approve.html", context)

    def revert_to_draft_view(self, request, object_id):
        obj = self.get_object(request, object_id)
        if not obj:
            return HttpResponseRedirect(reverse("admin:posthog_datadeletionrequest_changelist"))

        if request.method != "POST":
            return HttpResponseRedirect(reverse("admin:posthog_datadeletionrequest_change", args=[obj.pk]))

        updated = DataDeletionRequest.objects.filter(
            pk=obj.pk,
            status__in=[RequestStatus.PENDING, RequestStatus.APPROVED],
        ).update(
            status=RequestStatus.DRAFT,
            approved=False,
            approved_by=None,
            approved_at=None,
            updated_at=timezone.now(),
        )

        if not updated:
            messages.error(request, "Only pending or approved requests can be moved back to draft.")
            return HttpResponseRedirect(reverse("admin:posthog_datadeletionrequest_change", args=[obj.pk]))

        obj.refresh_from_db()
        self.log_change(request, obj, "Reverted to draft: cleared approval.")
        messages.success(request, "Request moved back to draft.")
        return HttpResponseRedirect(reverse("admin:posthog_datadeletionrequest_change", args=[obj.pk]))
