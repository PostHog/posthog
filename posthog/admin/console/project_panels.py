from datetime import timedelta
from typing import cast

from django import forms
from django.conf import settings
from django.contrib import messages
from django.db.models import Model
from django.http import HttpRequest, HttpResponse
from django.utils import timezone

from posthog.admin.authorization import DELETION_AUTHORIZED_GROUP
from posthog.admin.console.panels import MAX_FACTS_PER_PANEL, Fact, Gate, Operation, Panel, ReasonForm, Tone
from posthog.admin.console.records import RECORD_TYPES
from posthog.admin.console.registry import console
from posthog.admin.console.team_panels import DEV_EXPERIENCE
from posthog.event_usage import get_request_analytics_properties, report_user_action
from posthog.helpers.impersonation import is_impersonated
from posthog.models.activity_logging.activity_log import Detail, log_activity
from posthog.models.project import Project
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.models.utils import UUIDT


@console.register_panel
class ProjectOverviewPanel(Panel):
    record = "project"
    key = "overview"
    title = "Overview"
    owner = DEV_EXPERIENCE
    order = 10

    def facts(self, obj: Model) -> list[Fact]:
        assert isinstance(obj, Project)
        facts = [
            Fact(
                label="Organization",
                value=obj.organization.name,
                href=RECORD_TYPES["organization"].url(obj.organization),
            ),
            Fact(label="Created", value=obj.created_at.strftime("%b %-d, %Y")),
        ]
        room = MAX_FACTS_PER_PANEL - len(facts)
        team_record = RECORD_TYPES["team"]
        teams = list(obj.teams.order_by("id").only("id", "name")[: room + 1])
        if not teams:
            return [*facts, Fact(label="Teams", value="This project has no teams.")]
        shown = teams if len(teams) <= room else teams[: room - 1]
        facts += [
            Fact(label=team.name, value=f"Team {team.pk}", mono=True, href=team_record.url(team)) for team in shown
        ]
        if len(shown) < len(teams):
            hidden = obj.teams.count() - len(shown)
            facts.append(Fact(label="More", value=f"{hidden} more teams. The raw record in Django admin lists all."))
        return facts


def _report_deletion(request: HttpRequest, project: Project, teams: list[Team]) -> None:
    user = cast(User, request.user)
    organization_id = cast(UUIDT, project.organization_id)
    was_impersonated = is_impersonated(request)
    analytics_props = get_request_analytics_properties(request)
    for team in teams:
        log_activity(
            organization_id=organization_id,
            team_id=team.pk,
            user=user,
            was_impersonated=was_impersonated,
            scope="Team",
            item_id=team.pk,
            activity="deleted",
            detail=Detail(name=str(team.name)),
        )
        report_user_action(user, "team deleted", team=team, analytics_props=analytics_props)
    log_activity(
        organization_id=organization_id,
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
            user, "project deleted", {"project_name": project.name}, team=teams[0], analytics_props=analytics_props
        )


def _bulk_deletes_disabled(request: HttpRequest) -> HttpResponse | None:
    if not settings.DISABLE_BULK_DELETES:
        return None
    messages.error(request, "Bulk deletes are temporarily disabled during a database migration. Try again later.")
    return HttpResponse(status=503)


def delete_project(request: HttpRequest, obj: Model, form: forms.Form | None) -> HttpResponse | None:
    # Temporal client modules are heavy, so they load only when staff run the operation.
    from temporalio.exceptions import WorkflowAlreadyStartedError  # noqa: PLC0415

    from posthog.temporal.delete_teams.dispatch import (  # noqa: PLC0415
        project_deletion_delay,
        start_delete_project_data_workflow,
    )

    assert isinstance(obj, Project)
    disabled = _bulk_deletes_disabled(request)
    if disabled is not None:
        return disabled

    teams = list(obj.teams.only("id", "name", "organization_id").all())
    deletion_delay = project_deletion_delay(obj)
    deletion_scheduled_at = timezone.now() + (deletion_delay or timedelta())
    # Claim the project first, so two staff members who submit at once start one workflow, not two.
    claimed_project = Project.objects.filter(pk=obj.pk, is_pending_deletion=False).update(
        is_pending_deletion=True,
        deletion_scheduled_at=deletion_scheduled_at,
    )
    if not claimed_project:
        messages.error(request, f"Project {obj.name} ({obj.pk}) is already pending deletion.")
        return HttpResponse(status=409)

    try:
        start_delete_project_data_workflow(
            team_ids=[team.pk for team in teams],
            project_id=obj.pk,
            user_id=cast(User, request.user).id,
            project_name=obj.name,
            start_delay=(
                max(deletion_scheduled_at - timezone.now(), timedelta()) if deletion_delay is not None else None
            ),
        )
    except WorkflowAlreadyStartedError:
        messages.error(request, f"A deletion workflow is already running for project {obj.name} ({obj.pk}).")
        return HttpResponse(status=409)
    except Exception as error:
        Project.objects.filter(pk=obj.pk, deletion_scheduled_at=deletion_scheduled_at).update(
            is_pending_deletion=False,
            deletion_scheduled_at=None,
        )
        messages.error(request, f"Failed to start deletion workflow: {error}")
        return HttpResponse(status=500)

    _report_deletion(request, obj, teams)
    messages.success(request, f"Started deletion workflow for project {obj.name} ({obj.pk}).")
    return None


def delete_project_now(request: HttpRequest, obj: Model, form: forms.Form | None) -> HttpResponse | None:
    from temporalio.common import WorkflowIDConflictPolicy  # noqa: PLC0415

    from posthog.temporal.delete_teams.dispatch import start_delete_project_data_workflow  # noqa: PLC0415

    assert isinstance(obj, Project)
    disabled = _bulk_deletes_disabled(request)
    if disabled is not None:
        return disabled

    now = timezone.now()
    deletion_scheduled_at = obj.deletion_scheduled_at
    # Only a run that still waits can move to now. Once the scheduled time passes, the workflow already deletes.
    claimed_immediate_deletion = Project.objects.filter(
        pk=obj.pk,
        is_pending_deletion=True,
        deletion_scheduled_at=deletion_scheduled_at,
        deletion_scheduled_at__gt=now,
    ).update(deletion_scheduled_at=now)
    if not claimed_immediate_deletion:
        messages.error(
            request, f"The deletion state for project {obj.name} ({obj.pk}) has changed. Refresh and try again."
        )
        return HttpResponse(status=409)

    try:
        start_delete_project_data_workflow(
            team_ids=list(obj.teams.values_list("id", flat=True)),
            project_id=obj.pk,
            user_id=cast(User, request.user).id,
            project_name=obj.name,
            start_delay=None,
            id_conflict_policy=WorkflowIDConflictPolicy.TERMINATE_EXISTING,
        )
    except Exception as error:
        Project.objects.filter(pk=obj.pk, deletion_scheduled_at=now).update(
            deletion_scheduled_at=deletion_scheduled_at,
        )
        messages.error(request, f"Could not start deletion now: {error}. The scheduled deletion is unchanged.")
        return HttpResponse(status=500)
    messages.success(request, f"Started deletion for project {obj.name} ({obj.pk}).")
    return None


# Staff access alone must not start an irreversible deletion, so the ClickHouse team decides who may.
DELETION_GATE = Gate.group(DELETION_AUTHORIZED_GROUP)


@console.register_panel
class ProjectDeletionPanel(Panel):
    record = "project"
    key = "deletion"
    title = "Deletion"
    owner = DEV_EXPERIENCE
    order = 10
    danger = True

    def facts(self, obj: Model) -> list[Fact]:
        assert isinstance(obj, Project)
        if not obj.is_deletion_pending():
            return [Fact(label="Status", value="Not scheduled")]
        if obj.can_cancel_deletion():
            assert obj.deletion_scheduled_at is not None
            when = obj.deletion_scheduled_at.strftime("%b %-d, %Y %H:%M UTC")
            return [Fact(label="Status", value=f"Deletes on {when}", tone=Tone.WARNING)]
        return [Fact(label="Status", value="Deleting", tone=Tone.DESTRUCTIVE)]

    def operations(self, obj: Model) -> list[Operation]:
        assert isinstance(obj, Project)
        if not obj.is_deletion_pending():
            return [
                Operation(
                    key="delete",
                    label="Delete project",
                    handler=delete_project,
                    danger=True,
                    description=(
                        "Starts the workflow that deletes the project, its teams and all their data. A project "
                        "with ingested events waits before the delete starts. If a workflow is already running "
                        "for this project, PostHog does not start a second one."
                    ),
                    form_class=ReasonForm,
                    undo_hint=(
                        "While the deletion waits, an admin of the project can cancel it in the project settings. "
                        "Once it starts, it cannot be undone."
                    ),
                    gate=DELETION_GATE,
                )
            ]
        if obj.can_cancel_deletion():
            return [
                Operation(
                    key="delete-now",
                    label="Delete now",
                    handler=delete_project_now,
                    danger=True,
                    description=(
                        "Cancels the scheduled run and starts the deletion right away. If the start fails, "
                        "the original schedule stays."
                    ),
                    form_class=ReasonForm,
                    undo_hint="This cannot be undone. The project and all its data are deleted.",
                    gate=DELETION_GATE,
                )
            ]
        return []


# The panel, not the form: each deletion operation is offered only in one deletion state, so its form would 404.
for old in ("trigger-deletion", "delete-now"):
    console.register_moved_action(
        old_path=f"admin/posthog/project/<int:pk>/{old}/", record="project", target="#panel-deletion"
    )
