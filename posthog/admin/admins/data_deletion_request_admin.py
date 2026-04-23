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
    event_match_params,
    event_match_sql_fragment,
    jsonhas_expr,
)

CRITERIA_FIELDS = {"request_type", "events", "delete_all_events", "properties", "start_time", "end_time"}
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

    class Meta:
        model = DataDeletionRequest
        fields = "__all__"


def _build_event_filter(obj) -> tuple[str, dict]:
    """Build the WHERE clause and params for matching events."""
    return event_match_sql_fragment(obj), event_match_params(obj)


def _build_property_filter(obj) -> tuple[str, dict]:
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
    return filter_clause, params


def _fetch_stats(team_id: int, extra_filter: str, params: dict) -> dict:
    """Run event count + parts size queries against ClickHouse."""
    from posthog.clickhouse.client import sync_execute

    with tags_context(
        product=Product.INTERNAL,
        feature=Feature.DATA_DELETION,
        team_id=team_id,
        workload=Workload.OFFLINE,
        query_type="delete_event_count",
    ):
        # nosemgrep: clickhouse-fstring-param-audit (extra_filter is built from internal helpers, not user input)
        event_result = sync_execute(
            f"""
            SELECT
                count() AS events,
                count(DISTINCT _part) AS parts,
                min(timestamp) AS min_ts,
                max(timestamp) AS max_ts
            FROM sharded_events
            WHERE team_id = %(team_id)s
              AND timestamp >= %(start_time)s
              AND timestamp < %(end_time)s
              {extra_filter}
            """,
            params,
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

        # nosemgrep: clickhouse-fstring-param-audit (extra_filter from internal helpers; cluster from Django settings)
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
                  {extra_filter}
            ) AS matched ON p.name = matched.name
            WHERE p.table = 'sharded_events'
              AND p.active
            """,
            params,
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
    extra_filter, params = _build_event_filter(obj)
    return _fetch_stats(obj.team_id, extra_filter, params)


def fetch_property_deletion_stats(obj: DataDeletionRequest):
    """Count events with matching properties and affected parts for a property removal request."""
    if not obj.properties:
        raise ValueError("Cannot fetch stats for a property removal request with no properties specified.")
    extra_filter, params = _build_property_filter(obj)
    return _fetch_stats(obj.team_id, extra_filter, params)


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
                    "notes",
                    "requires_approval",
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
        super().save_model(request, obj, form, change)

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        obj = self.get_object(request, object_id)
        if obj:
            if obj.request_type == RequestType.PROPERTY_REMOVAL and not obj.properties:
                messages.warning(request, "This is a property removal request but no properties are specified.")
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
        can_submit = not missing_properties

        if request.method == "POST":
            if not can_submit:
                messages.error(request, "Cannot submit: property removal request requires at least one property.")
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
