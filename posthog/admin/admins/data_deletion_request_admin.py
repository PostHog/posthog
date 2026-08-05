import ast

from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html

from posthog.models.data_deletion_request import (
    AUTO_APPROVE_INTERVAL_MINUTES,
    AUTO_APPROVE_MAX_EVENTS,
    DataDeletionRequest,
    ExecutionMode,
    RequestStatus,
    RequestType,
    build_deletion_count_query,
    count_remaining_for_request,
    fetch_deletion_stats,
    invalidate_compiled_predicate_cache,
    refresh_deletion_stats,
)

CRITERIA_FIELDS = {
    "request_type",
    "events",
    "delete_all_events",
    "properties",
    "person_properties",
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

PERSON_REMOVAL_FIELDS = (
    "person_uuids",
    "person_distinct_ids",
    "person_drop_profiles",
    "person_drop_events",
    "person_drop_recordings",
)

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

    class Meta:
        model = DataDeletionRequest
        exclude = PERSON_REMOVAL_FIELDS

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request_type = self.fields.get("request_type")
        if isinstance(request_type, forms.ChoiceField):
            request_type.choices = [
                (value, label) for value, label in RequestType.choices if value != RequestType.PERSON_REMOVAL
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
            extra_context["can_retry"] = (
                obj.status == RequestStatus.FAILED and request.user.groups.filter(name=CLICKHOUSE_TEAM_GROUP).exists()
            )
            extra_context["retry_url"] = reverse("admin:posthog_datadeletionrequest_retry", args=[obj.pk])
            extra_context["can_verify"] = request.user.groups.filter(name=CLICKHOUSE_TEAM_GROUP).exists()
            extra_context["verify_url"] = reverse("admin:posthog_datadeletionrequest_verify", args=[obj.pk])

            # ClickHouse stats are calculated from this page (works for any status).
            extra_context["fetch_stats_url"] = reverse("admin:posthog_datadeletionrequest_fetch_stats", args=[obj.pk])
            extra_context["preview_stats_url"] = reverse(
                "admin:posthog_datadeletionrequest_preview_stats", args=[obj.pk]
            )
            extra_context["is_clickhouse_team"] = request.user.groups.filter(name=CLICKHOUSE_TEAM_GROUP).exists()
            preview_stats = request.session.pop("data_deletion_preview_stats", None)
            if preview_stats and str(preview_stats.get("obj_pk")) != str(obj.pk):
                # Belongs to a different request — drop it rather than mislead the operator.
                preview_stats = None
            extra_context["preview_stats"] = preview_stats

            if self._is_locked(obj):
                # Locked requests have no editable fields — hide the misleading Save row.
                extra_context["show_save"] = False
                extra_context["show_save_and_continue"] = False
                extra_context["show_save_and_add_another"] = False
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
                "<path:object_id>/preview-stats/",
                self.admin_site.admin_view(self.preview_stats_view),
                name="posthog_datadeletionrequest_preview_stats",
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
            path(
                "<path:object_id>/retry/",
                self.admin_site.admin_view(self.retry_view),
                name="posthog_datadeletionrequest_retry",
            ),
            path(
                "<path:object_id>/verify/",
                self.admin_site.admin_view(self.verify_view),
                name="posthog_datadeletionrequest_verify",
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

        missing_properties = (
            obj.request_type == RequestType.PROPERTY_REMOVAL and not obj.properties and not obj.person_properties
        )
        missing_person_selectors = obj.request_type == RequestType.PERSON_REMOVAL and not (
            obj.person_uuids or obj.person_distinct_ids
        )
        missing_person_drop_flag = obj.request_type == RequestType.PERSON_REMOVAL and not (
            obj.person_drop_profiles or obj.person_drop_events or obj.person_drop_recordings
        )
        can_submit = not (missing_properties or missing_person_selectors or missing_person_drop_flag)
        # Only event removals are ever auto-approved, so they're the only ones offered the opt-out.
        # Everything else about eligibility (the time range, the size) is time-dependent and left to
        # the sweep job, which re-evaluates it against stats it fetches itself.
        auto_approve_candidate = obj.request_type == RequestType.EVENT_REMOVAL

        if request.method == "POST":
            if missing_properties:
                messages.error(
                    request,
                    "Cannot submit: property removal request requires at least one property or person_property.",
                )
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
            # The checkbox only posts when ticked. A request that can't be auto-approved at all still
            # gets True: the field means "a human must approve this", and leaving it False would hide
            # the request from the changelist's "requires approval" filter — on precisely the requests
            # a reviewer needs to find.
            requires_approval = not auto_approve_candidate or bool(request.POST.get("requires_approval"))
            return self._submit_for_approval(request, obj, requires_approval=requires_approval)

        context = {
            **self.admin_site.each_context(request),
            "obj": obj,
            "missing_properties": missing_properties,
            "missing_person_selectors": missing_person_selectors,
            "missing_person_drop_flag": missing_person_drop_flag,
            "is_person_removal": obj.request_type == RequestType.PERSON_REMOVAL,
            "can_submit": can_submit,
            "auto_approve_candidate": auto_approve_candidate,
            # Thousands separators are applied here — django.contrib.humanize isn't installed.
            "auto_approve_max_events": f"{AUTO_APPROVE_MAX_EVENTS:,}",
            "auto_approve_interval_minutes": AUTO_APPROVE_INTERVAL_MINUTES,
            "opts": self.model._meta,
            "title": f"Submit deletion request {obj.pk}",
        }
        return TemplateResponse(request, "admin/posthog/datadeletionrequest/submit.html", context)

    def _submit_for_approval(
        self, request: HttpRequest, obj: DataDeletionRequest, *, requires_approval: bool
    ) -> HttpResponse:
        """Move the request draft → pending. Approval is somebody else's job, human or scheduled."""
        updated = DataDeletionRequest.objects.filter(
            pk=obj.pk,
            status=RequestStatus.DRAFT,
        ).update(
            status=RequestStatus.PENDING,
            requires_approval=requires_approval,
            updated_at=timezone.now(),
        )
        if not updated:
            messages.error(request, "Request is no longer in draft status.")
            return HttpResponseRedirect(reverse("admin:posthog_datadeletionrequest_change", args=[obj.pk]))
        obj.refresh_from_db()
        self.log_change(request, obj, "Submitted: status changed from draft to pending.")
        if requires_approval:
            messages.success(request, "Request submitted and is now pending ClickHouse Team approval.")
        else:
            messages.success(
                request,
                f"Request submitted and is now pending. The auto-approval job will check it within the next "
                f"{AUTO_APPROVE_INTERVAL_MINUTES} minutes and approve it if it matches fewer than "
                f"{AUTO_APPROVE_MAX_EVENTS:,} events.",
            )
        return HttpResponseRedirect(reverse("admin:posthog_datadeletionrequest_change", args=[obj.pk]))

    def fetch_stats_view(self, request, object_id):
        obj = self.get_object(request, object_id)
        if not obj:
            return HttpResponseRedirect(reverse("admin:posthog_datadeletionrequest_changelist"))

        if request.method != "POST":
            return HttpResponseRedirect(reverse("admin:posthog_datadeletionrequest_change", args=[obj.pk]))

        if obj.request_type == RequestType.PERSON_REMOVAL:
            # No ClickHouse query yet for person_removal — just count selectors.
            obj.count = len(obj.person_uuids) + len(obj.person_distinct_ids)
            obj.stats_calculated_at = timezone.now()
            obj.save(update_fields=["count", "stats_calculated_at", "updated_at"])
            self.log_change(request, obj, "Counted person_removal selectors.")
            messages.success(request, f"Selector count: {obj.count} person target(s).")
            return HttpResponseRedirect(reverse("admin:posthog_datadeletionrequest_change", args=[obj.pk]))

        try:
            stats = refresh_deletion_stats(obj, user_id=request.user.id)
            self.log_change(request, obj, "Fetched ClickHouse stats.")
            messages.success(request, f"Stats fetched: {stats['count']:,} matching events found.")
        except Exception as e:
            messages.error(request, f"Failed to fetch stats: {e}")

        return HttpResponseRedirect(reverse("admin:posthog_datadeletionrequest_change", args=[obj.pk]))

    def preview_stats_view(self, request, object_id):
        """ClickHouse-Team-only ephemeral stats run.

        Runs the same ClickHouse queries as ``fetch_stats_view`` but does **not**
        persist anything to the model — useful while iterating on a predicate.
        Results are stashed in the session and rendered on the next change page
        render under a separate "Preview (not saved)" block.
        """
        obj = self.get_object(request, object_id)
        if not obj:
            return HttpResponseRedirect(reverse("admin:posthog_datadeletionrequest_changelist"))

        if not request.user.groups.filter(name=CLICKHOUSE_TEAM_GROUP).exists():
            messages.error(request, "Only ClickHouse Team members can preview stats.")
            return HttpResponseRedirect(reverse("admin:posthog_datadeletionrequest_change", args=[obj.pk]))

        if request.method != "POST":
            return HttpResponseRedirect(reverse("admin:posthog_datadeletionrequest_change", args=[obj.pk]))

        if obj.request_type == RequestType.PERSON_REMOVAL:
            count = len(obj.person_uuids) + len(obj.person_distinct_ids)
            request.session["data_deletion_preview_stats"] = {
                "obj_pk": str(obj.pk),
                "count": count,
                "calculated_at": timezone.now().isoformat(),
            }
            messages.info(request, f"Preview selector count: {count} person target(s). Not saved.")
            return HttpResponseRedirect(reverse("admin:posthog_datadeletionrequest_change", args=[obj.pk]))

        try:
            stats = fetch_deletion_stats(obj, user_id=request.user.id)
            request.session["data_deletion_preview_stats"] = {
                "obj_pk": str(obj.pk),
                "count": stats["count"],
                "part_count": stats["part_count"],
                "parts_size": stats["parts_size"],
                "parts_row_count": stats["parts_row_count"],
                "min_timestamp": stats["min_timestamp"].isoformat() if stats["min_timestamp"] else None,
                "max_timestamp": stats["max_timestamp"].isoformat() if stats["max_timestamp"] else None,
                "calculated_at": timezone.now().isoformat(),
            }
            messages.info(
                request,
                f"Preview stats: {stats['count']:,} matching events. Not saved to the request.",
            )
        except Exception as e:
            messages.error(request, f"Failed to preview stats: {e}")

        return HttpResponseRedirect(reverse("admin:posthog_datadeletionrequest_change", args=[obj.pk]))

    def approve_view(self, request, object_id):
        obj = self.get_object(request, object_id)
        if not obj:
            return HttpResponseRedirect(reverse("admin:posthog_datadeletionrequest_changelist"))

        if not request.user.groups.filter(name=CLICKHOUSE_TEAM_GROUP).exists():
            messages.error(request, "Only ClickHouse Team members can approve deletion requests.")
            return HttpResponseRedirect(reverse("admin:posthog_datadeletionrequest_change", args=[obj.pk]))

        supports_deferred = obj.request_type == RequestType.EVENT_REMOVAL
        default_execution_mode = ExecutionMode.DEFERRED if supports_deferred else ExecutionMode.IMMEDIATE

        if request.method == "POST":
            execution_mode = request.POST.get("execution_mode", default_execution_mode)
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
            "default_execution_mode": default_execution_mode,
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
            approved_automatically=False,
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

    def retry_view(self, request, object_id):
        obj = self.get_object(request, object_id)
        if not obj:
            return HttpResponseRedirect(reverse("admin:posthog_datadeletionrequest_changelist"))

        if request.method != "POST":
            return HttpResponseRedirect(reverse("admin:posthog_datadeletionrequest_change", args=[obj.pk]))

        if not request.user.groups.filter(name=CLICKHOUSE_TEAM_GROUP).exists():
            messages.error(request, "Only ClickHouse Team members can retry deletion requests.")
            return HttpResponseRedirect(reverse("admin:posthog_datadeletionrequest_change", args=[obj.pk]))

        # Re-promote FAILED → APPROVED so the pickup sensor relaunches the job.
        # approved_by / approved_at are preserved — the retry re-executes the same approval.
        # attempt_count and last_executed_at are bumped by the load_* op when execution actually starts.
        updated = DataDeletionRequest.objects.filter(
            pk=obj.pk,
            status=RequestStatus.FAILED,
        ).update(status=RequestStatus.APPROVED, updated_at=timezone.now())

        if not updated:
            messages.error(request, "Only failed requests can be retried.")
            return HttpResponseRedirect(reverse("admin:posthog_datadeletionrequest_change", args=[obj.pk]))

        obj.refresh_from_db()
        next_attempt = obj.attempt_count + 1
        self.log_change(request, obj, f"Retry triggered (attempt #{next_attempt}): status FAILED → APPROVED.")
        messages.success(
            request,
            "Request requeued. The pickup sensor will launch a new run on its next tick.",
        )
        return HttpResponseRedirect(reverse("admin:posthog_datadeletionrequest_change", args=[obj.pk]))

    def verify_view(self, request, object_id):
        obj = self.get_object(request, object_id)
        if not obj:
            return HttpResponseRedirect(reverse("admin:posthog_datadeletionrequest_changelist"))

        if request.method != "POST":
            return HttpResponseRedirect(reverse("admin:posthog_datadeletionrequest_change", args=[obj.pk]))

        if not request.user.groups.filter(name=CLICKHOUSE_TEAM_GROUP).exists():
            messages.error(request, "Only ClickHouse Team members can verify deletion requests.")
            return HttpResponseRedirect(reverse("admin:posthog_datadeletionrequest_change", args=[obj.pk]))

        if obj.request_type == RequestType.PERSON_REMOVAL:
            messages.warning(
                request,
                "Automated verification isn't available for person removal requests — verify manually.",
            )
            return HttpResponseRedirect(reverse("admin:posthog_datadeletionrequest_change", args=[obj.pk]))

        try:
            remaining = count_remaining_for_request(obj)
        except Exception as e:
            messages.error(request, f"Failed to verify: {e}")
            return HttpResponseRedirect(reverse("admin:posthog_datadeletionrequest_change", args=[obj.pk]))

        if remaining:
            messages.warning(
                request,
                f"{remaining} matching row(s) still present in ClickHouse. "
                f"Left {obj.get_status_display().lower()} — re-run after the next scheduled deletion.",
            )
            return HttpResponseRedirect(reverse("admin:posthog_datadeletionrequest_change", args=[obj.pk]))

        prior_status = obj.status
        promoted = (
            DataDeletionRequest.objects.filter(pk=obj.pk)
            .exclude(status=RequestStatus.COMPLETED)
            .update(status=RequestStatus.COMPLETED, updated_at=timezone.now())
        )
        if promoted:
            obj.refresh_from_db()
            self.log_change(request, obj, f"Verified: 0 matching rows remain, status {prior_status} → completed.")
            messages.success(request, "Verified — no matching rows remain. Marked completed.")
        else:
            messages.info(request, "Verified — no matching rows remain. Already completed.")
        return HttpResponseRedirect(reverse("admin:posthog_datadeletionrequest_change", args=[obj.pk]))
