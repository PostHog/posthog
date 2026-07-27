from typing import cast

from django.conf import settings
from django.contrib import admin, messages
from django.shortcuts import redirect
from django.template.loader import render_to_string
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from posthog.admin.authorization import can_trigger_admin_deletion
from posthog.admin.inlines.organization_member_for_related_inline import OrganizationMemberForRelatedInline
from posthog.admin.inlines.team_inline import TeamInline
from posthog.models import Project


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "name",
        "organization_link",
        "organization_id",
        "created_at",
    )
    list_display_links = ("id", "name")
    list_select_related = ("organization",)
    search_fields = (
        "id",
        "name",
        "organization__id",
        "organization__name",
    )
    autocomplete_fields = ["organization"]
    readonly_fields = ["id", "created_at", "updated_at", "trigger_deletion_display"]
    fieldsets = (
        (
            None,
            {
                "fields": (
                    "id",
                    "name",
                    "organization",
                    "product_description",
                    "is_pending_deletion",
                    "created_at",
                    "updated_at",
                )
            },
        ),
        ("Danger zone", {"fields": ("trigger_deletion_display",)}),
    )
    inlines = [OrganizationMemberForRelatedInline, TeamInline]

    def organization_link(self, project: Project):
        return format_html(
            '<a href="{}">{}</a>',
            reverse("admin:posthog_organization_change", args=[project.organization.pk]),
            project.organization.name,
        )

    @admin.display(description="Danger zone")
    def trigger_deletion_display(self, project: Project):
        if not project.pk:
            return "-"
        # No csrf_token needed in the partial: the button posts the surrounding admin change
        # form (which carries the token) to the action URL via formaction.
        # nosemgrep: python.django.security.audit.avoid-mark-safe.avoid-mark-safe (admin-only, renders trusted template)
        return mark_safe(
            render_to_string(
                "admin/deletion_button.html",
                {
                    "action_url": reverse("admin:project_trigger_deletion", args=[project.pk]),
                    "button_label": "Trigger deletion",
                    "confirm_message": (
                        f'Trigger deletion for project "{project.name}" ({project.pk})? '
                        "This starts an irreversible Temporal workflow that deletes the project and all its data."
                    ),
                    "notice": (
                        "Before triggering, make sure no Temporal deletion workflow is already running for this "
                        "project. Starting a second one while another is mid-flight can cause clashing deletes."
                    ),
                },
            )
        )

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<path:project_id>/trigger-deletion/",
                self.admin_site.admin_view(self.trigger_deletion_view),
                name="project_trigger_deletion",
            ),
        ]
        return custom_urls + urls

    def trigger_deletion_view(self, request, project_id):
        from temporalio.exceptions import WorkflowAlreadyStartedError

        from posthog.event_usage import report_user_action
        from posthog.helpers.impersonation import is_impersonated
        from posthog.models.activity_logging.activity_log import Detail, log_activity
        from posthog.models.utils import UUIDT
        from posthog.temporal.delete_teams.dispatch import start_delete_project_data_workflow

        change_url = reverse("admin:posthog_project_change", args=[project_id])

        try:
            project = Project.objects.get(id=project_id)
        except Project.DoesNotExist:
            messages.error(request, f"Project with id {project_id} not found.")
            return redirect(reverse("admin:posthog_project_changelist"))

        if request.method != "POST":
            return redirect(change_url)

        # Staff access alone must not authorize a destructive delete; require explicit
        # membership in the deletion-authorized group (Django's model permissions are not a
        # real gate here — User.is_superuser mirrors is_staff, so every staff user passes).
        if not can_trigger_admin_deletion(request):
            messages.error(request, "You do not have permission to delete this project.")
            return redirect(change_url)

        if settings.DISABLE_BULK_DELETES:
            messages.error(
                request, "Bulk deletes are temporarily disabled during a database migration. Try again later."
            )
            return redirect(change_url)

        if project.is_pending_deletion:
            messages.error(request, f"Project {project.name} ({project.pk}) is already being deleted.")
            return redirect(change_url)

        teams = list(project.teams.only("id", "name", "organization_id").all())
        team_ids = [team.pk for team in teams]

        user = request.user
        organization_id = project.organization_id

        # Mark pending before dispatch so the project is locked out even if this write and the
        # workflow start race; mirrors the API deletion path.
        project.is_pending_deletion = True
        project.save(update_fields=["is_pending_deletion"])

        try:
            start_delete_project_data_workflow(
                team_ids=team_ids,
                project_id=project.pk,
                user_id=user.id,
                project_name=project.name,
            )
        except WorkflowAlreadyStartedError:
            messages.error(
                request, f"A deletion workflow is already running for project {project.name} ({project.pk})."
            )
            return redirect(change_url)
        except Exception as e:
            # Dispatch failed, so no workflow is running; unlock the project so it can be retried.
            project.is_pending_deletion = False
            project.save(update_fields=["is_pending_deletion"])
            messages.error(request, f"Failed to start deletion workflow: {e}")
            return redirect(change_url)

        was_impersonated = is_impersonated(request)
        for team in teams:
            log_activity(
                organization_id=cast(UUIDT, organization_id),
                team_id=team.pk,
                user=user,
                was_impersonated=was_impersonated,
                scope="Team",
                item_id=team.pk,
                activity="deleted",
                detail=Detail(name=str(team.name)),
            )
            report_user_action(user, "team deleted", team=team, request=request)
        log_activity(
            organization_id=cast(UUIDT, organization_id),
            team_id=project.pk,
            user=user,
            was_impersonated=was_impersonated,
            scope="Project",
            item_id=project.pk,
            activity="deleted",
            detail=Detail(name=str(project.name)),
        )
        if teams:
            report_user_action(
                user,
                "project deleted",
                {"project_name": project.name},
                team=teams[0],
                request=request,
            )

        messages.success(request, f"Started deletion workflow for project {project.name} ({project.pk}).")
        return redirect(change_url)
