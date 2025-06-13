from django import forms
from django.contrib import admin
from django.contrib import messages
from django.shortcuts import render, redirect
from django.urls import path, reverse
from posthog.clickhouse.client import sync_execute
from posthog.models.async_deletion.async_deletion import AsyncDeletion, DeletionType
from posthog.models.team import Team
import json


class CustomEventDeletionForm(forms.Form):
    team_id = forms.IntegerField(
        label="Team ID", widget=forms.NumberInput(attrs={"class": "vTextField", "style": "width: 200px"})
    )
    predicate = forms.CharField(
        label="SQL WHERE Predicate",
        help_text="Example: properties.$geoip_disable = 1 OR properties.error_type = 'timeout'",
        widget=forms.Textarea(attrs={"rows": 3, "cols": 80, "class": "vLargeTextField"}),
    )
    preview_only = forms.BooleanField(
        required=False,
        initial=True,
        label="Preview Only",
        help_text="Check to preview events that would be deleted. Uncheck to actually create the deletion.",
    )


class AsyncDeletionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "deletion_type",
        "group_type_index",
        "team_id",
        "key",
        "created_by",
        "created_at",
        "delete_verified_at",
    )
    list_filter = ("deletion_type", "delete_verified_at")
    search_fields = ("key",)
    change_list_template = "admin/posthog/asyncdeletion/change_list.html"

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "custom-event-deletion/",
                self.admin_site.admin_view(self.custom_event_deletion_view),
                name="posthog_asyncdeletion_custom_deletion",
            ),
        ]
        return custom_urls + urls

    def custom_event_deletion_view(self, request):
        if not request.user.is_staff:
            messages.error(request, "You must be staff to access this feature.")
            return redirect(reverse("admin:posthog_asyncdeletion_changelist"))

        preview_results = None

        if request.method == "POST":
            form = CustomEventDeletionForm(request.POST)
            if form.is_valid():
                team_id = form.cleaned_data["team_id"]
                predicate = form.cleaned_data["predicate"]
                preview_only = form.cleaned_data["preview_only"]

                # Verify team exists
                try:
                    Team.objects.get(id=team_id)
                except Team.DoesNotExist:
                    messages.error(request, f"Team with ID {team_id} does not exist.")
                    return render(
                        request,
                        "admin/posthog/asyncdeletion/custom_event_deletion.html",
                        {"form": form, "title": "Custom Event Deletion"},
                    )

                # Build query to preview/count events
                count_query = f"""
                    SELECT count() as count
                    FROM events
                    WHERE team_id = %(team_id)s
                    AND ({predicate})
                """

                sample_query = f"""
                    SELECT
                        uuid,
                        event,
                        timestamp,
                        distinct_id,
                        properties
                    FROM events
                    WHERE team_id = %(team_id)s
                    AND ({predicate})
                    ORDER BY timestamp DESC
                    LIMIT 10
                """

                try:
                    # Get count
                    count_result = sync_execute(count_query, {"team_id": team_id}, settings={"max_execution_time": 30})
                    event_count = count_result[0][0] if count_result else 0

                    # Get samples
                    sample_results = sync_execute(
                        sample_query, {"team_id": team_id}, settings={"max_execution_time": 30}
                    )

                    preview_results = {
                        "count": event_count,
                        "samples": [
                            {
                                "uuid": str(row[0]),
                                "event": row[1],
                                "timestamp": row[2],
                                "distinct_id": row[3],
                                "properties": json.dumps(row[4], indent=2) if row[4] else "{}",
                            }
                            for row in sample_results
                        ],
                    }

                    if not preview_only and event_count > 0:
                        # Create the async deletion
                        async_deletion = AsyncDeletion.objects.create(
                            deletion_type=DeletionType.Custom, team_id=team_id, key=predicate, created_by=request.user
                        )
                        messages.success(
                            request,
                            f"Created async deletion #{async_deletion.id} for {event_count:,} events in team {team_id}",
                        )
                        return redirect(reverse("admin:posthog_asyncdeletion_changelist"))

                except Exception as e:
                    messages.error(request, f"Error executing query: {str(e)}")

        else:
            form = CustomEventDeletionForm()

        return render(
            request,
            "admin/posthog/asyncdeletion/custom_event_deletion.html",
            {"form": form, "preview_results": preview_results, "title": "Custom Event Deletion"},
        )
