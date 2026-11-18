from collections.abc import Callable
from functools import partial
from typing import cast

from django import forms
from django.apps import apps
from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Model
from django.http import HttpRequest, HttpResponse
from django.urls import reverse

import structlog
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.admin.authorization import DELETION_AUTHORIZED_GROUP
from posthog.admin.console.panels import Fact, Gate, Operation, Panel, ReasonForm
from posthog.admin.console.records import RECORD_TYPES
from posthog.admin.console.registry import console
from posthog.admin.console.team_panels import DEV_EXPERIENCE
from posthog.admin.console.tools import Cell, ConsoleTool, Notice, Page, Row, Table
from posthog.event_usage import report_organization_deleted, report_organization_deletion_initiated
from posthog.models.organization import Organization
from posthog.models.user import User
from posthog.person_db_router import PERSONS_DB_MODELS
from posthog.temporal.delete_teams.dispatch import start_delete_organization_workflow

from products.batch_exports.backend.facade import api as batch_exports_api

logger = structlog.get_logger(__name__)

# Default-database models that organization deletion removes in bulk, as (app_label.ModelName, team field, label).
# This mirrors delete_bulky_postgres_data() in posthog/models/team/util.py. When bulk delete changes, update it.
# Batch exports are counted separately, because the count must leave out deleted exports, as team deletion does.
BULK_DELETE_MODEL_REGISTRY: tuple[tuple[str, str, str], ...] = (
    ("early_access_features.EarlyAccessFeature", "team_id", "Early access features"),
    ("error_tracking.ErrorTrackingIssueFingerprintV2", "team_id", "Error tracking fingerprints"),
)

# Persons-database models that bulk delete removes too. The console cannot count them from the default database.
# Keys match the lowercase model names in person_db_router.PERSONS_DB_MODELS.
BULK_DELETE_PERSONS_DB_MODELS: dict[str, str] = {
    "cohortpeople": "cohort people",
    "featureflaghashkeyoverride": "feature flag overrides",
    "group": "groups",
    "grouptypemapping": "group type mappings",
    "person": "persons",
    "persondistinctid": "person distinct IDs",
}

PREVIEW_TEAMS_LIMIT = 100
DATA_TOOL_KEY = "organization-data"


def _count_row(label: str, count: Callable[[], int]) -> Row:
    try:
        return Row(cells=(Cell(text=label), Cell(text=f"{count():,}")))
    except Exception as error:
        return Row(cells=(Cell(text=label), Cell(text=f"Could not count: {error}", muted=True)))


def _model_count(model_label: str, team_field: str, team_ids: list[int]) -> int:
    model_class = apps.get_model(model_label)
    # nosemgrep: orm-field-injection -- team_field comes from the hardcoded BULK_DELETE_MODEL_REGISTRY, not user input
    return model_class.objects.filter(**{f"{team_field}__in": team_ids}).count()


def _persons_database_notice() -> Notice:
    for model_name in BULK_DELETE_PERSONS_DB_MODELS:
        if model_name not in PERSONS_DB_MODELS:
            raise ValueError(f"{model_name} is listed in BULK_DELETE_PERSONS_DB_MODELS but not in PERSONS_DB_MODELS")
    names = sorted(BULK_DELETE_PERSONS_DB_MODELS.values())
    return Notice(
        text=f"Deletion also removes {', '.join(names[:-1])} and {names[-1]} from the persons database. "
        "They are not counted here."
    )


def data_counts(organization: Organization) -> list[Notice | Table]:
    """The rows organization deletion removes from the default database, and a note on the persons database."""
    team_ids = list(organization.teams.values_list("id", flat=True))
    if not team_ids:
        return [Notice(text="The organization has no teams, so it holds no team data.")]
    rows = [
        _count_row(label, partial(_model_count, model_label, team_field, team_ids))
        for model_label, team_field, label in BULK_DELETE_MODEL_REGISTRY
    ]
    rows.append(_count_row("Batch exports", lambda: batch_exports_api.count_batch_exports_for_teams(team_ids)))
    return [Table(columns=("Data", "Rows"), rows=tuple(rows)), _persons_database_notice()]


def data_tool_url(organization: Organization) -> str:
    return f"{reverse('admin_console_tool', kwargs={'tool_key': DATA_TOOL_KEY})}?organization={organization.pk}"


def preview_deletion(request: HttpRequest, obj: Model, form: forms.Form) -> Page:
    assert isinstance(obj, Organization)
    team_record = RECORD_TYPES["team"]
    teams = list(obj.teams.order_by("id").only("id", "name")[: PREVIEW_TEAMS_LIMIT + 1])
    shown = teams[:PREVIEW_TEAMS_LIMIT]
    blocks: list[Notice | Table] = [
        Notice(
            text=(
                "Before you confirm, check in Temporal that no deletion workflow already runs for this organization. "
                "Two workflows at the same time can make the deletes clash."
            )
        ),
        Table(
            columns=("Team", "ID"),
            rows=tuple(
                Row(cells=(Cell(text=team.name, href=team_record.url(team)), Cell(text=str(team.pk), mono=True)))
                for team in shown
            ),
            empty_text="The organization has no teams. Deletion removes only the organization.",
        ),
    ]
    if len(teams) > len(shown):
        blocks.append(Notice(text=f"Deletion also removes {obj.teams.count() - len(shown)} more teams."))
    if teams:
        # Exact counts can take long on a large organization, so the preview links to them instead of
        # blocking the confirm on them.
        blocks.append(
            Notice(
                text="Deletion also removes the team data of these teams.",
                link_text="See row counts",
                href=data_tool_url(obj),
            )
        )
    return Page(blocks=tuple(blocks))


def delete_organization(request: HttpRequest, obj: Model, form: forms.Form | None) -> HttpResponse | None:
    assert isinstance(obj, Organization)
    if settings.DISABLE_BULK_DELETES:
        messages.error(request, "Bulk deletes are paused during a database migration. Try again later.")
        return HttpResponse(status=503)
    # Claim the organization in one update, so two staff members who confirm at once start one workflow.
    # Marking it pending also locks the members out, even while the workflow start below is still running.
    claimed = Organization.objects.filter(pk=obj.pk, is_pending_deletion=False).update(is_pending_deletion=True)
    if not claimed:
        messages.error(request, f"Organization {obj.name} is already being deleted.")
        return HttpResponse(status=409)

    user = cast(User, request.user)
    try:
        report_organization_deleted(user, obj)
        report_organization_deletion_initiated(user, obj)
        teams = list(obj.teams.only("id", "name"))
        start_delete_organization_workflow(
            team_ids=[team.pk for team in teams],
            organization_id=str(obj.pk),
            user_id=user.pk,
            organization_name=obj.name,
            project_names=[team.name for team in teams],
        )
    except WorkflowAlreadyStartedError:
        messages.error(request, f"A deletion workflow is already running for organization {obj.name}.")
        return HttpResponse(status=409)
    except Exception as error:
        logger.exception("admin_console_organization_deletion_dispatch_failed", organization_id=str(obj.pk))
        # The workflow did not start, so unlock the organization for another try.
        Organization.objects.filter(pk=obj.pk).update(is_pending_deletion=False)
        messages.error(request, f"Could not start the deletion workflow: {error}")
        return HttpResponse(status=500)
    messages.success(request, f"Started the deletion workflow for organization {obj.name}.")
    return None


@console.register_panel
class OrganizationDeletionPanel(Panel):
    record = "organization"
    key = "deletion"
    title = "Deletion"
    owner = DEV_EXPERIENCE
    order = 10
    danger = True

    def facts(self, obj: Model) -> list[Fact]:
        assert isinstance(obj, Organization)
        # The counts can be slow on large tables, and this panel renders on every organization page load.
        return [Fact(label="Data", value="Counts of the data deletion removes", href=data_tool_url(obj))]

    def operations(self, obj: Model) -> list[Operation]:
        assert isinstance(obj, Organization)
        if obj.is_pending_deletion:
            return []
        return [
            Operation(
                key="delete",
                label="Delete organization",
                handler=delete_organization,
                preview=preview_deletion,
                danger=True,
                description=(
                    "Locks the organization for its members at once, then starts the workflow that deletes its "
                    "projects and all their data."
                ),
                form_class=ReasonForm,
                undo_hint="This cannot be undone. Deleted data cannot be restored.",
                # Staff access alone must not delete an organization, because the deletion cannot be undone.
                gate=Gate.group(DELETION_AUTHORIZED_GROUP),
            )
        ]


@console.register_tool
class OrganizationDataTool(ConsoleTool):
    key = DATA_TOOL_KEY
    title = "Organization data"
    owner = DEV_EXPERIENCE
    group = "Organizations"
    description = "Counts the data that deleting one organization removes."

    def page(self, request: HttpRequest) -> Page:
        organization_id = request.GET.get("organization", "")
        try:
            organization = Organization.objects.filter(pk=organization_id).first() if organization_id else None
        except ValidationError:
            organization = None
        if organization is None:
            return Page(
                blocks=(Notice(text="Open an organization's data counts from the Deletion panel on its page."),)
            )
        return Page(
            blocks=(
                Notice(
                    text=f"Deleting {organization.name} removes the data below.",
                    link_text="Back to the organization",
                    href=RECORD_TYPES["organization"].url(organization),
                ),
                *data_counts(organization),
            )
        )


console.register_moved_action(
    old_path="admin/posthog/organization/<uuid:pk>/trigger-deletion/", record="organization", target="#panel-deletion"
)
console.register_moved_page(
    old_path="admin/posthog/organization/<uuid:pk>/model-counts/",
    title="Child model counts",
    url="/admin/console/tools/organization-data/?organization={pk}",
)
