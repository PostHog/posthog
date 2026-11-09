from collections.abc import Callable
from functools import partial
from typing import cast

from django import forms
from django.apps import apps
from django.conf import settings
from django.contrib import messages
from django.db.models import Model
from django.http import HttpRequest, HttpResponse

import structlog
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.admin.authorization import DELETION_AUTHORIZED_GROUP
from posthog.admin.console.panels import Fact, Gate, Operation, Panel, ReasonForm
from posthog.admin.console.records import RECORD_TYPES
from posthog.admin.console.registry import console
from posthog.admin.console.team_panels import DEV_EXPERIENCE
from posthog.admin.console.tools import Cell, Notice, Page, Row, Table
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


def _count_fact(label: str, count: Callable[[], int]) -> Fact:
    try:
        return Fact(label=label, value=f"{count():,}")
    except Exception as error:
        return Fact(label=label, value=f"Could not count: {error}")


def _model_count(model_label: str, team_field: str, team_ids: list[int]) -> int:
    model_class = apps.get_model(model_label)
    # nosemgrep: orm-field-injection -- team_field comes from the hardcoded BULK_DELETE_MODEL_REGISTRY, not user input
    return model_class.objects.filter(**{f"{team_field}__in": team_ids}).count()


def _persons_database_fact() -> Fact:
    for model_name in BULK_DELETE_PERSONS_DB_MODELS:
        if model_name not in PERSONS_DB_MODELS:
            raise ValueError(f"{model_name} is listed in BULK_DELETE_PERSONS_DB_MODELS but not in PERSONS_DB_MODELS")
    names = sorted(BULK_DELETE_PERSONS_DB_MODELS.values())
    return Fact(
        label="Persons database",
        value=f"Deletion removes {', '.join(names[:-1])} and {names[-1]} too. They are not counted here.",
    )


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
    report_organization_deleted(user, obj)
    report_organization_deletion_initiated(user, obj)
    teams = list(obj.teams.only("id", "name"))
    try:
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
    danger = True

    def facts(self, obj: Model) -> list[Fact]:
        assert isinstance(obj, Organization)
        team_ids = list(obj.teams.values_list("id", flat=True))
        if not team_ids:
            return [Fact(label="Data", value="The organization has no teams, so it holds no team data.")]
        facts = [
            _count_fact(label, partial(_model_count, model_label, team_field, team_ids))
            for model_label, team_field, label in BULK_DELETE_MODEL_REGISTRY
        ]
        facts.append(_count_fact("Batch exports", lambda: batch_exports_api.count_batch_exports_for_teams(team_ids)))
        facts.append(_persons_database_fact())
        return facts

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
