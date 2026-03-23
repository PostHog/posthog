from django.contrib import admin, messages
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone

from posthog.models.data_deletion_request import RequestStatus

CRITERIA_FIELDS = {"request_type", "events", "properties", "start_time", "end_time"}


def fetch_event_deletion_stats(obj):
    """Count events and parts for an event removal request."""
    from posthog.clickhouse.client import sync_execute

    result = sync_execute(
        """
        SELECT
            count() as events,
            count(distinct _part) as parts
        FROM sharded_events
        WHERE team_id = %(team_id)s
          AND timestamp >= %(start_time)s
          AND timestamp < %(end_time)s
          AND event IN %(events)s
        """,
        {
            "team_id": obj.team_id,
            "start_time": obj.start_time,
            "end_time": obj.end_time,
            "events": obj.events,
        },
    )

    return {
        "count": result[0][0] if result else 0,
        "part_count": result[0][1] if result else 0,
        "parts_size": None,
    }


def fetch_property_deletion_stats(obj):
    """Count events that have any of the specified properties for a property removal request."""
    from posthog.clickhouse.client import sync_execute

    if len(obj.properties) == 1:
        property_filter = "JSONHas(properties, %(property)s)"
        params: dict = {
            "team_id": obj.team_id,
            "start_time": obj.start_time,
            "end_time": obj.end_time,
            "events": obj.events,
            "property": obj.properties[0],
        }
    else:
        property_filter = "hasAny(JSONExtractKeys(properties), %(properties)s)"
        params = {
            "team_id": obj.team_id,
            "start_time": obj.start_time,
            "end_time": obj.end_time,
            "events": obj.events,
            "properties": obj.properties,
        }

    result = sync_execute(
        f"""
        SELECT
            count() as events,
            count(distinct _part) as parts
        FROM sharded_events
        WHERE team_id = %(team_id)s
          AND timestamp >= %(start_time)s
          AND timestamp < %(end_time)s
          AND event IN %(events)s
          AND {property_filter}
        """,
        params,
    )

    return {
        "count": result[0][0] if result else 0,
        "part_count": result[0][1] if result else 0,
        "parts_size": None,
    }


def fetch_deletion_stats(obj):
    """Dispatch to the appropriate stats function based on request type."""
    if obj.request_type == "property_removal":
        return fetch_property_deletion_stats(obj)
    return fetch_event_deletion_stats(obj)


class DataDeletionRequestAdmin(admin.ModelAdmin):
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
        "count",
        "part_count",
        "parts_size",
        "stats_calculated_at",
        "created_at",
        "created_by",
        "updated_at",
        "updated_by",
        "approved",
        "approved_by",
        "approved_at",
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
                    "properties",
                    "notes",
                    "requires_approval",
                ),
            },
        ),
        (
            "ClickHouse stats",
            {
                "fields": ("count", "part_count", "parts_size", "stats_calculated_at"),
                "description": "Populated by executing a ClickHouse query. Not editable.",
            },
        ),
        (
            "Audit trail",
            {
                "fields": (
                    "created_by",
                    "created_at",
                    "updated_by",
                    "updated_at",
                    "approved",
                    "approved_by",
                    "approved_at",
                ),
            },
        ),
    )

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        elif form.changed_data and CRITERIA_FIELDS & set(form.changed_data):
            obj.updated_by = request.user
            obj.count = None
            obj.part_count = None
            obj.parts_size = None
            obj.stats_calculated_at = None
            if "events" in form.changed_data or "properties" in form.changed_data:
                if obj.status != RequestStatus.DRAFT:
                    obj.status = RequestStatus.DRAFT
                    messages.warning(request, "Events or properties were changed — status has been reset to draft.")
        if obj.request_type == "event_removal" and obj.properties:
            obj.properties = []
            messages.info(request, "Properties cleared — event removal requests do not use properties.")
        super().save_model(request, obj, form, change)

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        obj = self.get_object(request, object_id)
        if obj:
            if obj.request_type == "property_removal" and not obj.properties:
                messages.warning(request, "This is a property removal request but no properties are specified.")
            extra_context["is_draft"] = obj.status == RequestStatus.DRAFT
            extra_context["submit_url"] = reverse("admin:posthog_datadeletionrequest_submit", args=[obj.pk])
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
        ]
        return custom_urls + urls

    def submit_view(self, request, object_id):
        obj = self.get_object(request, object_id)
        if not obj:
            return HttpResponseRedirect(reverse("admin:posthog_datadeletionrequest_changelist"))

        if obj.status != RequestStatus.DRAFT:
            messages.error(request, "Only draft requests can be submitted.")
            return HttpResponseRedirect(reverse("admin:posthog_datadeletionrequest_change", args=[obj.pk]))

        missing_properties = obj.request_type == "property_removal" and not obj.properties
        can_submit = not missing_properties

        if request.method == "POST":
            if not can_submit:
                messages.error(request, "Cannot submit: property removal request requires at least one property.")
                return HttpResponseRedirect(reverse("admin:posthog_datadeletionrequest_change", args=[obj.pk]))
            obj.status = RequestStatus.PENDING
            obj.save(update_fields=["status", "updated_at"])
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
            obj.stats_calculated_at = timezone.now()
            obj.save(update_fields=["count", "part_count", "parts_size", "stats_calculated_at", "updated_at"])
            self.log_change(request, obj, "Fetched ClickHouse stats.")
            messages.success(request, f"Stats fetched: {stats['count']:,} matching events found.")
        except Exception as e:
            messages.error(request, f"Failed to fetch stats: {e}")

        return HttpResponseRedirect(reverse("admin:posthog_datadeletionrequest_submit", args=[obj.pk]))
