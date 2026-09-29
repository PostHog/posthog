from uuid import NAMESPACE_URL, UUID, uuid5

from django.db import connection, transaction

from posthog.models import Team, User
from posthog.models.team.team import DEPRECATED_ATTRS
from posthog.permissions import posthog_feature_flag_enabled

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.customer_analytics.backend.facade.constants import CUSTOMER_ANALYTICS_CUSTOMER_TASKS_FLAG
from products.customer_analytics.backend.facade.contracts import (
    CreateCustomerTaskInput,
    CustomerTaskAccessDenied,
    CustomerTaskNotFound,
    ReportCustomerTaskInput,
)
from products.customer_analytics.backend.logic.customer_tasks import (
    can_access_customer_task_object,
    create_customer_task,
    report_agent_result,
)
from products.customer_analytics.backend.models import CustomerTask
from products.workflows.backend.facade.api import get_workflow_owner_id


class WorkflowCustomerTaskOwnerInactive(Exception):
    pass


class WorkflowCustomerTaskProjectAccessDenied(Exception):
    pass


class WorkflowCustomerTasksDisabled(Exception):
    pass


class WorkflowCustomerTaskWorkflowMismatch(Exception):
    """The task names a loop of its own, and this workflow is not it."""


def _get_task_id(team_id: int, workflow_id: UUID, idempotency_key: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"posthog:customer-task:{team_id}:{workflow_id}:{idempotency_key}")


def get_workflow_customer_task_id(*, team_id: int, workflow_id: UUID, idempotency_key: str) -> UUID | None:
    task_id = _get_task_id(team_id, workflow_id, idempotency_key)
    return task_id if CustomerTask.objects.for_team(team_id).filter(id=task_id).exists() else None


def create_workflow_customer_task(
    *,
    team: Team,
    workflow_id: UUID,
    idempotency_key: str,
    input: CreateCustomerTaskInput,
    actor: User,
    user_access_control: UserAccessControl,
) -> UUID:
    task_id = _get_task_id(team.id, workflow_id, idempotency_key)
    with transaction.atomic():
        # Lock the invocation even before its task exists, so concurrent retries create one activity and assignment.
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s, hashtext(%s))", [team.id, str(task_id)])
        if CustomerTask.objects.for_team(team.id).filter(id=task_id).exists():
            return task_id
        if not user_access_control.has_project_access or not user_access_control.check_access_level_for_resource(
            "customer_task", "editor"
        ):
            raise CustomerTaskAccessDenied()
        task = create_customer_task(
            team=team, input=input, actor=actor, user_access_control=user_access_control, task_id=task_id
        )
        return task.id


def _get_team(team_id: int) -> Team:
    # `select_related` builds its columns from the related model rather than through `TeamManager`,
    # so re-apply its defer to the joined parent. Without it every task write in a child
    # environment re-reads the deprecated taxonomy columns, which TOAST out to megabytes per team.
    return (
        Team.objects.select_related("parent_team")
        .defer(*(f"parent_team__{attr}" for attr in DEPRECATED_ATTRS))
        .get(id=team_id)
    )


def _authorize_workflow_owner(*, team: Team, workflow_id: UUID) -> User:
    owner_id = get_workflow_owner_id(team_id=team.id, workflow_id=workflow_id)
    owner = User.objects.filter(id=owner_id).first()
    if owner is None or not owner.is_active:
        raise WorkflowCustomerTaskOwnerInactive()
    access = UserAccessControl(user=owner, team=team, organization_id=str(team.organization_id))
    if not access.has_project_access:
        raise WorkflowCustomerTaskProjectAccessDenied()
    if not posthog_feature_flag_enabled(
        CUSTOMER_ANALYTICS_CUSTOMER_TASKS_FLAG,
        str(owner.distinct_id),
        organization_id=team.organization_id,
        team_id=team.id,
    ):
        raise WorkflowCustomerTasksDisabled()
    return owner


def create_customer_task_from_workflow(
    *, team_id: int, workflow_id: UUID, idempotency_key: str, input: CreateCustomerTaskInput
) -> UUID:
    team = _get_team(team_id)
    canonical_team = team.parent_team or team
    # A verified retry acknowledges a committed task without granting access to its contents.
    existing_task_id = get_workflow_customer_task_id(
        team_id=canonical_team.id, workflow_id=workflow_id, idempotency_key=idempotency_key
    )
    if existing_task_id is not None:
        return existing_task_id
    owner = _authorize_workflow_owner(team=team, workflow_id=workflow_id)
    canonical_access = UserAccessControl(user=owner, team=canonical_team, organization_id=str(team.organization_id))
    return create_workflow_customer_task(
        team=canonical_team,
        workflow_id=workflow_id,
        idempotency_key=idempotency_key,
        input=input,
        actor=owner,
        user_access_control=canonical_access,
    )


def report_customer_task_from_workflow(
    *, team_id: int, workflow_id: UUID, task_id: UUID, idempotency_key: str, input: ReportCustomerTaskInput
) -> UUID:
    """Record a workflow's report on a task assigned to PostHog and settle the task.

    The workflow owner needs editor access to the task, as with any write. A retry with the
    same idempotency key is acknowledged without a second report.
    """
    team = _get_team(team_id)
    canonical_team = team.parent_team or team
    owner = _authorize_workflow_owner(team=team, workflow_id=workflow_id)
    canonical_access = UserAccessControl(user=owner, team=canonical_team, organization_id=str(team.organization_id))
    with transaction.atomic():
        task = (
            CustomerTask.objects.for_team(canonical_team.id)
            .select_for_update(of=("self",))
            .select_related("account")
            .filter(id=task_id)
            .first()
        )
        if task is None:
            raise CustomerTaskNotFound()
        if not can_access_customer_task_object(task=task, user_access_control=canonical_access, write=True):
            raise CustomerTaskAccessDenied()
        assigned_workflow_id = (task.properties.get("agent") or {}).get("hog_flow_id")
        if assigned_workflow_id and str(assigned_workflow_id) != str(workflow_id):
            raise WorkflowCustomerTaskWorkflowMismatch()
        report_agent_result(
            team=canonical_team, task=task, workflow_id=workflow_id, idempotency_key=idempotency_key, input=input
        )
    return task.id
