from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from uuid import UUID

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Case, CharField, F, IntegerField, Q, QuerySet, Value, When
from django.db.models.functions import Coalesce, Concat, Lower, NullIf, Trim
from django.utils import timezone

from posthog.models import OrganizationMembership, Team, User

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.customer_analytics.backend.facade import contracts
from products.customer_analytics.backend.facade.contracts import (
    CustomerTaskAccessDenied,
    CustomerTaskAccountNotFound,
    CustomerTaskArchived,
    CustomerTaskAssigneeCannotViewAccount,
    CustomerTaskAssigneeInvalid,
    CustomerTaskInvalidTransition,
)
from products.customer_analytics.backend.models import Account, CustomerTask, CustomerTaskActivity
from products.customer_analytics.backend.models.customer_task import CustomerTaskActivityType, CustomerTaskStatus

CUSTOMER_TASK_ACTIVITY_TYPE_CHOICES = CustomerTaskActivityType.choices
CUSTOMER_TASK_STATUS_CHOICES = CustomerTaskStatus.choices

_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    CustomerTaskStatus.OPEN.value: frozenset(
        {CustomerTaskStatus.IN_PROGRESS.value, CustomerTaskStatus.COMPLETED.value, CustomerTaskStatus.CANCELED.value}
    ),
    CustomerTaskStatus.IN_PROGRESS.value: frozenset(
        {CustomerTaskStatus.OPEN.value, CustomerTaskStatus.COMPLETED.value, CustomerTaskStatus.CANCELED.value}
    ),
    CustomerTaskStatus.COMPLETED.value: frozenset({CustomerTaskStatus.OPEN.value}),
    CustomerTaskStatus.CANCELED.value: frozenset({CustomerTaskStatus.OPEN.value}),
}


def _task_queryset(team_id: int) -> QuerySet[CustomerTask]:
    return CustomerTask.objects.for_team(team_id).select_related("account", "assigned_to", "completed_by", "created_by")


def _visible_account_queryset(team_id: int, user_access_control: UserAccessControl) -> QuerySet[Account]:
    accounts = Account.objects.for_team(team_id)
    return user_access_control.filter_queryset_by_access_level(accounts, resource="account")


def _task_by_id(queryset: QuerySet[CustomerTask], task_id: UUID | str) -> CustomerTask | None:
    try:
        return queryset.filter(id=task_id).first()
    except (DjangoValidationError, ValueError):
        return None


def _visible_task_queryset(team_id: int, user_access_control: UserAccessControl) -> QuerySet[CustomerTask]:
    visible_account_ids = _visible_account_queryset(team_id, user_access_control).values("id")
    account_filter = Q(account__isnull=True) | Q(account_id__in=visible_account_ids)
    if user_access_control.check_access_level_for_resource("customer_task", "viewer"):
        return _task_queryset(team_id).filter(account_filter)
    return _task_queryset(team_id).filter(assigned_to_id=user_access_control.user.id).filter(account_filter)


def _account_for_write(team_id: int, account_id: UUID | None, user_access_control: UserAccessControl) -> Account | None:
    if account_id is None:
        return None
    account = _visible_account_queryset(team_id, user_access_control).filter(id=account_id).first()
    if account is None:
        raise CustomerTaskAccountNotFound()
    return account


def _validate_assignee(
    *,
    team: Team,
    account: Account | None,
    assignee_id: int | None,
) -> User | None:
    if assignee_id is None:
        return None
    membership_exists = OrganizationMembership.objects.filter(
        organization_id=team.organization_id, user_id=assignee_id
    ).exists()
    if not membership_exists:
        raise CustomerTaskAssigneeInvalid()
    assignee = User.objects.filter(id=assignee_id).first()
    if assignee is None:
        raise CustomerTaskAssigneeInvalid()
    assignee_access = UserAccessControl(user=assignee, team=team)
    if not assignee_access.check_access_level_for_object(team, required_level="member"):
        raise CustomerTaskAssigneeInvalid()
    if account is not None and not assignee_access.check_access_level_for_object(account, required_level="viewer"):
        raise CustomerTaskAssigneeCannotViewAccount()
    return assignee


def _user_view(user: User | None) -> contracts.CustomerTaskUserView | None:
    if user is None:
        return None
    return contracts.CustomerTaskUserView(
        id=user.id, email=user.email, first_name=user.first_name, last_name=user.last_name
    )


def _task_view(task: CustomerTask, user_access_control: UserAccessControl) -> contracts.CustomerTaskView:
    account = (
        contracts.CustomerTaskAccountView(id=task.account.id, name=task.account.name)
        if task.account is not None
        else None
    )
    return contracts.CustomerTaskView(
        id=task.id,
        account=account,
        name=task.name,
        description=task.description,
        status=task.status,
        assigned_to=_user_view(task.assigned_to),
        due_at=task.due_at,
        completed_at=task.completed_at,
        completed_by=_user_view(task.completed_by),
        created_by=_user_view(task.created_by),
        archived_at=task.archived_at,
        created_at=task.created_at,
        updated_at=task.updated_at,
        can_edit=_can_edit(task, user_access_control),
    )


def _can_edit(task: CustomerTask, user_access_control: UserAccessControl) -> bool:
    return task.assigned_to_id == user_access_control.user.id or user_access_control.check_access_level_for_resource(
        "customer_task", "editor"
    )


def _timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat().replace("+00:00", "Z")


def _snapshot_account(account: Account | None) -> dict[str, object] | None:
    if account is None:
        return None
    return {"id": str(account.id), "name": account.name}


def _snapshot_user(user: User | None) -> dict[str, object] | None:
    if user is None:
        return None
    return {"id": user.id, "email": user.email, "first_name": user.first_name, "last_name": user.last_name}


def _changes(
    *,
    before_account: Account | None,
    after_account: Account | None,
    before_name: str | None,
    after_name: str | None,
    before_description: str | None,
    after_description: str | None,
    before_status: str | None,
    after_status: str | None,
    before_assignee: User | None,
    after_assignee: User | None,
    before_due_at: datetime | None,
    after_due_at: datetime | None,
) -> list[dict[str, object | None]]:
    values: Iterable[tuple[str, object | None, object | None]] = (
        ("account", _snapshot_account(before_account), _snapshot_account(after_account)),
        ("name", before_name, after_name),
        ("description", before_description, after_description),
        ("status", before_status, after_status),
        ("assigned_to", _snapshot_user(before_assignee), _snapshot_user(after_assignee)),
        ("due_at", _timestamp(before_due_at), _timestamp(after_due_at)),
    )
    return [{"field": field, "before": before, "after": after} for field, before, after in values if before != after]


def _record_activity(
    *, task: CustomerTask, activity_type: str, actor: User | None, changes: list[dict[str, object | None]]
) -> None:
    CustomerTaskActivity.objects.for_team(task.team_id).create(
        team_id=task.team_id,
        task=task,
        actor=actor,
        activity_type=activity_type,
        changes=changes,
    )


def _order_by_annotation(queryset: QuerySet[CustomerTask], annotation: str, descending: bool) -> QuerySet[CustomerTask]:
    ordering = F(annotation).desc(nulls_last=True) if descending else F(annotation).asc(nulls_last=True)
    return queryset.order_by(ordering, "id")


def _apply_ordering(queryset: QuerySet[CustomerTask], ordering: str) -> QuerySet[CustomerTask]:
    descending = ordering.startswith("-")
    field = ordering.removeprefix("-")
    if field == "status":
        queryset = queryset.alias(
            _ordering_status=Case(
                When(status=CustomerTaskStatus.OPEN, then=Value(0)),
                When(status=CustomerTaskStatus.IN_PROGRESS, then=Value(1)),
                When(status=CustomerTaskStatus.COMPLETED, then=Value(2)),
                When(status=CustomerTaskStatus.CANCELED, then=Value(3)),
                default=Value(4),
                output_field=IntegerField(),
            )
        )
        return _order_by_annotation(queryset, "_ordering_status", descending)
    if field == "assigned_to":
        queryset = queryset.alias(
            _ordering_assigned_to=Lower(
                Coalesce(
                    NullIf(Trim(Concat("assigned_to__first_name", Value(" "), "assigned_to__last_name")), Value("")),
                    "assigned_to__email",
                    output_field=CharField(),
                )
            )
        )
        return _order_by_annotation(queryset, "_ordering_assigned_to", descending)
    if field == "account":
        queryset = queryset.alias(_ordering_account=Lower("account__name"))
        return _order_by_annotation(queryset, "_ordering_account", descending)
    if field == "name":
        queryset = queryset.alias(_ordering_name=Lower("name"))
        return _order_by_annotation(queryset, "_ordering_name", descending)
    return _order_by_annotation(queryset, field, descending)


def list_customer_tasks(
    *,
    team_id: int,
    user_access_control: UserAccessControl,
    filters: contracts.CustomerTaskListFilters,
    offset: int,
    limit: int,
) -> tuple[list[contracts.CustomerTaskView], int]:
    queryset = _visible_task_queryset(team_id, user_access_control)
    if filters.search:
        queryset = queryset.filter(Q(name__icontains=filters.search) | Q(description__icontains=filters.search))
    if filters.account_id is not None:
        queryset = queryset.filter(account_id=filters.account_id)
    if filters.assigned_to == "me":
        queryset = queryset.filter(assigned_to_id=user_access_control.user.id)
    elif filters.assigned_to == "unassigned":
        queryset = queryset.filter(assigned_to_id__isnull=True)
    elif filters.assigned_to:
        queryset = queryset.filter(assigned_to_id=int(filters.assigned_to))
    if filters.statuses:
        queryset = queryset.filter(status__in=filters.statuses)
    if filters.archive_state == "active":
        queryset = queryset.filter(archived_at__isnull=True)
    elif filters.archive_state == "archived":
        queryset = queryset.filter(archived_at__isnull=False)
    if filters.due_after is not None:
        queryset = queryset.filter(due_at__gte=filters.due_after)
    if filters.due_before is not None:
        queryset = queryset.filter(due_at__lt=filters.due_before)
    if filters.has_due_at is not None:
        queryset = queryset.filter(due_at__isnull=not filters.has_due_at)

    if filters.ordering is None:
        queryset = queryset.order_by(F("due_at").asc(nulls_last=True), "-updated_at", "id")
    else:
        queryset = _apply_ordering(queryset, filters.ordering)
    count = queryset.count()
    return [_task_view(task, user_access_control) for task in queryset[offset : offset + limit]], count


def get_customer_task(
    *, team_id: int, task_id: UUID | str, user_access_control: UserAccessControl
) -> contracts.CustomerTaskView | None:
    task = _task_by_id(_visible_task_queryset(team_id, user_access_control), task_id)
    return _task_view(task, user_access_control) if task is not None else None


def _task_for_write(
    *, team_id: int, task_id: UUID | str, user_access_control: UserAccessControl
) -> CustomerTask | None:
    return _task_by_id(_visible_task_queryset(team_id, user_access_control), task_id)


def create_customer_task(
    *,
    team: Team,
    input: contracts.CreateCustomerTaskInput,
    actor: User | None,
    user_access_control: UserAccessControl,
) -> contracts.CustomerTaskView:
    account = _account_for_write(team.id, input.account_id, user_access_control)
    assignee = _validate_assignee(team=team, account=account, assignee_id=input.assigned_to_id)
    completed_at = timezone.now() if input.status == CustomerTaskStatus.COMPLETED else None
    completed_by = actor if completed_at is not None and actor is not None else assignee if completed_at else None
    with transaction.atomic():
        task = CustomerTask.objects.for_team(team.id).create(
            team_id=team.id,
            account=account,
            name=input.name,
            description=input.description,
            assigned_to=assignee,
            due_at=input.due_at,
            status=input.status,
            completed_at=completed_at,
            completed_by=completed_by,
            created_by=actor,
        )
        _record_activity(
            task=task,
            activity_type=CustomerTaskActivityType.CREATED,
            actor=actor,
            changes=_changes(
                before_account=None,
                after_account=account,
                before_name=None,
                after_name=task.name,
                before_description=None,
                after_description=task.description,
                before_status=None,
                after_status=task.status,
                before_assignee=None,
                after_assignee=assignee,
                before_due_at=None,
                after_due_at=task.due_at,
            ),
        )
    return _task_view(task, user_access_control)


def update_customer_task(
    *,
    team: Team,
    task_id: UUID | str,
    input: contracts.UpdateCustomerTaskInput,
    actor: User | None,
    user_access_control: UserAccessControl,
) -> contracts.CustomerTaskView | None:
    task = _task_for_write(team_id=team.id, task_id=task_id, user_access_control=user_access_control)
    if task is None:
        return None
    if not can_access_customer_task_object(task=task, user_access_control=user_access_control, write=True):
        raise CustomerTaskAccessDenied()
    if task.archived_at is not None:
        raise CustomerTaskArchived()

    before_account = task.account
    before_name = task.name
    before_description = task.description
    before_status = task.status
    before_assignee = task.assigned_to
    before_due_at = task.due_at
    semantic_change = (
        (input.account_id_provided and input.account_id != task.account_id)
        or (input.name_provided and input.name != task.name)
        or (input.description_provided and input.description != task.description)
        or (input.assigned_to_id_provided and input.assigned_to_id != task.assigned_to_id)
        or (input.due_at_provided and input.due_at != task.due_at)
        or (input.status_provided and input.status != task.status)
    )
    if not semantic_change:
        return _task_view(task, user_access_control)

    account = _account_for_write(
        team.id, input.account_id if input.account_id_provided else task.account_id, user_access_control
    )
    assignee_id = input.assigned_to_id if input.assigned_to_id_provided else task.assigned_to_id
    assignee = _validate_assignee(team=team, account=account, assignee_id=assignee_id)
    requested_status = input.status if input.status_provided else task.status
    if (
        input.status_provided
        and requested_status != task.status
        and requested_status not in _ALLOWED_TRANSITIONS[task.status]
    ):
        raise CustomerTaskInvalidTransition(task.status, requested_status or "")

    if requested_status == CustomerTaskStatus.COMPLETED and task.status != CustomerTaskStatus.COMPLETED:
        completed_at = timezone.now()
        completed_by = actor if actor is not None else assignee
    elif requested_status == CustomerTaskStatus.OPEN and task.status == CustomerTaskStatus.COMPLETED:
        completed_at = None
        completed_by = None
    else:
        completed_at = task.completed_at
        completed_by = task.completed_by

    task.account = account
    task.name = input.name if input.name_provided else task.name
    task.description = input.description if input.description_provided else task.description
    task.assigned_to = assignee
    task.due_at = input.due_at if input.due_at_provided else task.due_at
    task.status = requested_status
    task.completed_at = completed_at
    task.completed_by = completed_by
    with transaction.atomic():
        task.save()
        changes = _changes(
            before_account=before_account,
            after_account=task.account,
            before_name=before_name,
            after_name=task.name,
            before_description=before_description,
            after_description=task.description,
            before_status=before_status,
            after_status=task.status,
            before_assignee=before_assignee,
            after_assignee=task.assigned_to,
            before_due_at=before_due_at,
            after_due_at=task.due_at,
        )
        if changes:
            _record_activity(task=task, activity_type=CustomerTaskActivityType.UPDATED, actor=actor, changes=changes)
    return _task_view(task, user_access_control)


def archive_customer_task(
    *, team_id: int, task_id: UUID | str, actor: User | None, user_access_control: UserAccessControl
) -> contracts.CustomerTaskView | None:
    task = _task_for_write(team_id=team_id, task_id=task_id, user_access_control=user_access_control)
    if task is None:
        return None
    if not can_access_customer_task_object(task=task, user_access_control=user_access_control, write=True):
        raise CustomerTaskAccessDenied()
    if task.archived_at is None:
        with transaction.atomic():
            task.archived_at = timezone.now()
            task.save(update_fields=["archived_at", "updated_at"])
            _record_activity(task=task, activity_type=CustomerTaskActivityType.ARCHIVED, actor=actor, changes=[])
    return _task_view(task, user_access_control)


def restore_customer_task(
    *, team_id: int, task_id: UUID | str, actor: User | None, user_access_control: UserAccessControl
) -> contracts.CustomerTaskView | None:
    task = _task_for_write(team_id=team_id, task_id=task_id, user_access_control=user_access_control)
    if task is None:
        return None
    if not can_access_customer_task_object(task=task, user_access_control=user_access_control, write=True):
        raise CustomerTaskAccessDenied()
    if task.archived_at is not None:
        with transaction.atomic():
            task.archived_at = None
            task.save(update_fields=["archived_at", "updated_at"])
            _record_activity(task=task, activity_type=CustomerTaskActivityType.RESTORED, actor=actor, changes=[])
    return _task_view(task, user_access_control)


def list_customer_task_activities(
    *, team_id: int, task_id: UUID | str, user_access_control: UserAccessControl, offset: int, limit: int
) -> tuple[list[contracts.CustomerTaskActivityView], int] | None:
    task = _task_for_write(team_id=team_id, task_id=task_id, user_access_control=user_access_control)
    if task is None or not can_access_customer_task_object(
        task=task, user_access_control=user_access_control, write=False
    ):
        return None
    queryset = CustomerTaskActivity.objects.for_team(team_id).filter(task_id=task.id).select_related("actor")
    count = queryset.count()
    activities = queryset.order_by("-created_at", "-id")[offset : offset + limit]
    return [
        contracts.CustomerTaskActivityView(
            id=activity.id,
            activity_type=activity.activity_type,
            changes=[
                contracts.CustomerTaskChange(
                    field=str(change.get("field", "")),
                    before=change.get("before"),
                    after=change.get("after"),
                )
                for change in activity.changes
                if isinstance(change, dict)
            ],
            actor=_user_view(activity.actor),
            created_at=activity.created_at,
        )
        for activity in activities
    ], count


def can_access_customer_task_object(*, task: CustomerTask, user_access_control: UserAccessControl, write: bool) -> bool:
    if (
        task.account_id is not None
        and not _visible_account_queryset(task.team_id, user_access_control).filter(id=task.account_id).exists()
    ):
        return False
    if task.assigned_to_id == user_access_control.user.id:
        return True
    return user_access_control.check_access_level_for_resource("customer_task", "editor" if write else "viewer")
