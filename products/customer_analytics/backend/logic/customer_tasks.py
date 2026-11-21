from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from functools import cached_property
from typing import cast
from uuid import UUID

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.db.models import Case, CharField, F, IntegerField, Prefetch, Q, QuerySet, Value, When
from django.db.models.functions import Coalesce, Concat, Lower, NullIf, Trim
from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.models import OrganizationMembership, Team, User
from posthog.models.tag import Tag, tagify
from posthog.models.tagged_item import TaggedItem
from posthog.paging import Page, PageRequest
from posthog.queryset_paging import select_page

from products.access_control.backend.facade import (
    api as access_control_api,
    contracts as access_control_contracts,
)
from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.customer_analytics.backend.constants import CUSTOMER_TASK_MAX_TAGS
from products.customer_analytics.backend.facade import contracts
from products.customer_analytics.backend.facade.contracts import (
    CustomerTaskAccessDenied,
    CustomerTaskAccountNotFound,
    CustomerTaskArchived,
    CustomerTaskAssigneeCannotViewAccount,
    CustomerTaskAssigneeInvalid,
    CustomerTaskInvalidTransition,
    CustomerTaskRoleNotFound,
    CustomerTaskTagLimitExceeded,
)
from products.customer_analytics.backend.models import Account, CustomerTask, CustomerTaskActivity
from products.customer_analytics.backend.models.customer_task import CustomerTaskActivityType, CustomerTaskStatus

CUSTOMER_TASK_ACTIVITY_TYPE_CHOICES = CustomerTaskActivityType.choices
CUSTOMER_TASK_STATUS_CHOICES = CustomerTaskStatus.choices


@frozen
class _CustomerTaskActivityPage:
    activities: Page[CustomerTaskActivity]
    visible_account_ids: frozenset[str]


@frozen
class _CustomerTaskWrite:
    task: CustomerTask
    before_assignee: User | None
    activity: CustomerTaskActivity
    tag_names: list[str] | None = None


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
    return (
        CustomerTask.objects.for_team(team_id)
        .select_related("account", "assigned_to", "completed_by", "created_by")
        .prefetch_related(
            # The same attribute the tagged-item serializer mixin reads, so one query serves a whole page.
            Prefetch("tagged_items", queryset=TaggedItem.objects.select_related("tag"), to_attr="prefetched_tags")
        )
    )


def _get_customer_task_tagged_items(task: CustomerTask) -> list[TaggedItem]:
    tagged_items = getattr(task, "prefetched_tags", None)
    return tagged_items if tagged_items is not None else list(task.tagged_items.select_related("tag"))


def list_customer_task_tag_names(task: CustomerTask) -> list[str]:
    return sorted(item.tag.name for item in _get_customer_task_tagged_items(task))


def _parse_tag_names(tags: Iterable[str]) -> list[str]:
    return sorted({name for name in (tagify(tag) for tag in tags) if name})


def _resolve_tag_names(current: list[str], tags: Iterable[str], tags_mode: str) -> list[str]:
    requested = set(_parse_tag_names(tags))
    if tags_mode == "add":
        resolved = set(current) | requested
        if len(resolved) > max(len(current), CUSTOMER_TASK_MAX_TAGS):
            raise CustomerTaskTagLimitExceeded()
        return sorted(resolved)
    if tags_mode == "remove":
        return sorted(set(current) - requested)
    return sorted(requested)


def _set_customer_task_tags(team_id: int, updates: Iterable[tuple[CustomerTask, list[str]]]) -> None:
    """Use bulk writes so tag changes appear only in the access-checked task history."""
    pending: list[tuple[CustomerTask, dict[str, TaggedItem], set[str]]] = []
    names_to_add: set[str] = set()
    removed_ids: set[UUID] = set()
    removed_tag_ids: set[UUID] = set()
    for task, names in updates:
        requested = set(names)
        kept = {}
        for item in _get_customer_task_tagged_items(task):
            if item.tag.name in requested:
                kept[item.tag.name] = item
            else:
                removed_ids.add(item.pk)
                removed_tag_ids.add(item.tag_id)
        missing = requested - kept.keys()
        names_to_add.update(missing)
        pending.append((task, kept, missing))

    # Concurrent transactions must insert shared tags in the same order to avoid deadlocks.
    tags = {name: Tag.objects.get_or_create(name=name, team_id=team_id)[0] for name in sorted(names_to_add)}
    added: list[TaggedItem] = []
    for task, kept, missing in pending:
        new_items = [TaggedItem.for_content_object(tags[name], task) for name in missing]
        added.extend(new_items)
        task.prefetched_tags = [*kept.values(), *new_items]  # type: ignore[attr-defined]

    if added:
        TaggedItem.objects.bulk_create(added)
    if removed_ids:
        TaggedItem.objects.filter(team_id=team_id, pk__in=removed_ids).delete()
        Tag.objects.filter(team_id=team_id, id__in=removed_tag_ids, tagged_items__isnull=True).delete()


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
    return user_access_control.filter_queryset_by_access_level(
        _task_queryset(team_id), resource="customer_task"
    ).filter(account_filter)


def _account_for_write(team_id: int, account_id: UUID | None, user_access_control: UserAccessControl) -> Account | None:
    if account_id is None:
        return None
    account = _visible_account_queryset(team_id, user_access_control).filter(id=account_id).first()
    if account is None:
        raise CustomerTaskAccountNotFound()
    return account


def _validate_assignee_access(*, team: Team, account: Account | None, access: UserAccessControl) -> None:
    if not access.check_access_level_for_object(team, required_level="member"):
        raise CustomerTaskAssigneeInvalid()
    if account is not None and not access.check_access_level_for_object(account, required_level="viewer"):
        raise CustomerTaskAssigneeCannotViewAccount()


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
    _validate_assignee_access(team=team, account=account, access=UserAccessControl(user=assignee, team=team))
    return assignee


class _CustomerTaskBulkValidation:
    def __init__(
        self,
        *,
        team: Team,
        visible_tasks: list[CustomerTask],
        input: contracts.UpdateCustomerTaskInput,
        user_access_control: UserAccessControl,
    ) -> None:
        self.team = team
        self.user_access_control = user_access_control
        self.accounts = {task.account.id: task.account for task in visible_tasks if task.account is not None}
        self.assignee_ids = {task.assigned_to_id for task in visible_tasks if task.assigned_to_id is not None}
        if input.assigned_to_id_provided and input.assigned_to_id is not None:
            self.assignee_ids.add(input.assigned_to_id)
        self.validated_pairs: set[tuple[UUID | None, int]] = set()

    @cached_property
    def assignee_access(self) -> dict[int, UserAccessControl]:
        return UserAccessControl.for_user_ids(user_ids=self.assignee_ids, team=self.team)

    def can_edit(self, task: CustomerTask) -> bool:
        return self.user_access_control.check_access_level_for_object(task, required_level="editor")

    def get_account(self, account_id: UUID | None) -> Account | None:
        if account_id is None:
            return None
        if account_id not in self.accounts:
            account = _account_for_write(self.team.id, account_id, self.user_access_control)
            if account is None:
                raise CustomerTaskAccountNotFound()
            self.accounts[account_id] = account
        return self.accounts[account_id]

    def get_assignee(self, account: Account | None, assignee_id: int | None) -> User | None:
        if assignee_id is None:
            return None
        access = self.assignee_access.get(assignee_id)
        if access is None:
            raise CustomerTaskAssigneeInvalid()
        pair = (account.id if account is not None else None, assignee_id)
        if pair not in self.validated_pairs:
            _validate_assignee_access(team=self.team, account=account, access=access)
            self.validated_pairs.add(pair)
        return access.user


def _set_customer_task_assignee_access(
    *,
    task: CustomerTask,
    organization_id: UUID,
    before_assignee: User | None,
    after_assignee: User | None,
    actor: User | None,
) -> None:
    if before_assignee == after_assignee:
        return

    for assignee, access_level in ((before_assignee, None), (after_assignee, "editor")):
        if assignee is None:
            continue
        membership_id = (
            OrganizationMembership.objects.filter(organization_id=organization_id, user_id=assignee.id)
            .values_list("id", flat=True)
            .first()
        )
        if membership_id is None:
            if access_level is not None:
                raise CustomerTaskAssigneeInvalid()
            continue
        access_control_api.set_object_access_control(
            team_id=task.team_id,
            input=access_control_contracts.SetObjectAccessControlInput(
                resource="customer_task",
                resource_id=str(task.id),
                organization_member_id=membership_id,
                access_level=access_level,
                created_by_id=actor.id if actor is not None else None,
            ),
        )


def can_edit_customer_task(task: CustomerTask, user_access_control: UserAccessControl) -> bool:
    return task.archived_at is None and user_access_control.check_access_level_for_object(task, "editor")


def can_restore_customer_task(task: CustomerTask, user_access_control: UserAccessControl) -> bool:
    return task.archived_at is not None and user_access_control.check_access_level_for_object(task, "editor")


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
    before_tags: list[str] | None,
    after_tags: list[str] | None,
) -> list[dict[str, object | None]]:
    values: Iterable[tuple[str, object | None, object | None]] = (
        ("account", _snapshot_account(before_account), _snapshot_account(after_account)),
        ("name", before_name, after_name),
        ("description", before_description, after_description),
        ("status", before_status, after_status),
        ("assigned_to", _snapshot_user(before_assignee), _snapshot_user(after_assignee)),
        ("due_at", _timestamp(before_due_at), _timestamp(after_due_at)),
        ("tags", before_tags or None, after_tags or None),
    )
    before_account_id = str(before_account.id) if before_account is not None else None
    after_account_id = str(after_account.id) if after_account is not None else None
    changes: list[dict[str, object | None]] = []
    for field, before, after in values:
        if before == after:
            continue
        change: dict[str, object | None] = {"field": field, "before": before, "after": after}
        if field != "account":
            change["before_account_id"] = before_account_id
            change["after_account_id"] = after_account_id
        changes.append(change)
    return changes


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


def remove_customer_task_assignee_access_for_account(*, team: Team, account_id: UUID) -> None:
    tasks = (
        CustomerTask.objects.for_team(team.id)
        .select_related("assigned_to")
        .filter(account_id=account_id, assigned_to__isnull=False)
    )
    for task in tasks.iterator():
        _set_customer_task_assignee_access(
            task=task,
            organization_id=team.organization_id,
            before_assignee=task.assigned_to,
            after_assignee=None,
            actor=None,
        )


def _list_role_member_user_ids(team_id: int, user_access_control: UserAccessControl, role_id: UUID) -> list[int]:
    team = user_access_control.team
    if team is None or team.id != team_id:
        team = Team.objects.only("organization_id").get(id=team_id)
    if not access_control_api.role_belongs_to_organization(role_id=role_id, organization_id=team.organization_id):
        raise CustomerTaskRoleNotFound()
    return access_control_api.valid_role_member_user_ids(role_id=role_id)


def list_customer_tasks(
    *,
    team_id: int,
    user_access_control: UserAccessControl,
    filters: contracts.CustomerTaskListFilters,
    page: PageRequest,
) -> Page[CustomerTask]:
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
    if filters.assigned_role_id is not None:
        queryset = queryset.filter(
            assigned_to_id__in=_list_role_member_user_ids(team_id, user_access_control, filters.assigned_role_id)
        )
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
    if tag_names := _parse_tag_names(filters.tags):
        # A subquery rather than .distinct(), which Postgres rejects next to the ordering aliases.
        tagged_task_ids = CustomerTask.objects.for_team(team_id).filter(tagged_items__tag__name__in=tag_names)
        queryset = queryset.filter(id__in=tagged_task_ids.values("id"))

    if filters.ordering is None:
        queryset = queryset.order_by(F("due_at").asc(nulls_last=True), "-updated_at", "id")
    else:
        queryset = _apply_ordering(queryset, filters.ordering)
    return select_page(queryset, page)


def get_customer_task(
    *, team_id: int, task_id: UUID | str, user_access_control: UserAccessControl
) -> CustomerTask | None:
    return _task_by_id(_visible_task_queryset(team_id, user_access_control), task_id)


def _task_for_write(
    *, team_id: int, task_id: UUID | str, user_access_control: UserAccessControl
) -> CustomerTask | None:
    queryset = _visible_task_queryset(team_id, user_access_control).select_for_update(of=("self",))
    return _task_by_id(queryset, task_id)


def create_customer_task(
    *,
    team: Team,
    input: contracts.CreateCustomerTaskInput,
    actor: User | None,
    user_access_control: UserAccessControl,
    task_id: UUID | None = None,
) -> CustomerTask:
    account = _account_for_write(team.id, input.account_id, user_access_control)
    assignee = _validate_assignee(team=team, account=account, assignee_id=input.assigned_to_id)
    completed_at = timezone.now() if input.status == CustomerTaskStatus.COMPLETED else None
    completed_by = actor if completed_at is not None and actor is not None else assignee if completed_at else None
    tag_names = _parse_tag_names(input.tags)
    with transaction.atomic():
        task = CustomerTask.objects.for_team(team.id).create(
            **({"id": task_id} if task_id is not None else {}),
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
        if tag_names:
            _set_customer_task_tags(team.id, [(task, tag_names)])
        _set_customer_task_assignee_access(
            task=task,
            organization_id=team.organization_id,
            before_assignee=None,
            after_assignee=assignee,
            actor=actor,
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
                before_tags=None,
                after_tags=tag_names,
            ),
        )
    return task


def _prepare_customer_task_update(
    *,
    team: Team,
    task: CustomerTask,
    input: contracts.UpdateCustomerTaskInput,
    actor: User | None,
    user_access_control: UserAccessControl,
    validation: _CustomerTaskBulkValidation | None = None,
) -> _CustomerTaskWrite | None:
    can_edit = (
        validation.can_edit(task)
        if validation is not None
        else can_access_customer_task_object(task=task, user_access_control=user_access_control, write=True)
    )
    if not can_edit:
        raise CustomerTaskAccessDenied()
    if task.archived_at is not None:
        raise CustomerTaskArchived()

    before_account = task.account
    before_name = task.name
    before_description = task.description
    before_status = task.status
    before_assignee = task.assigned_to
    before_due_at = task.due_at
    before_tags = list_customer_task_tag_names(task)
    after_tags = _resolve_tag_names(before_tags, input.tags, input.tags_mode) if input.tags_provided else before_tags
    semantic_change = (
        (input.account_id_provided and input.account_id != task.account_id)
        or (input.name_provided and input.name != task.name)
        or (input.description_provided and input.description != task.description)
        or (input.assigned_to_id_provided and input.assigned_to_id != task.assigned_to_id)
        or (input.due_at_provided and input.due_at != task.due_at)
        or (input.status_provided and input.status != task.status)
        or after_tags != before_tags
    )
    if not semantic_change:
        return None

    account_id = input.account_id if input.account_id_provided else task.account_id
    assignee_id = input.assigned_to_id if input.assigned_to_id_provided else task.assigned_to_id
    if validation is not None:
        account = validation.get_account(account_id)
        assignee = validation.get_assignee(account, assignee_id)
    else:
        account = _account_for_write(team.id, account_id, user_access_control)
        assignee = _validate_assignee(team=team, account=account, assignee_id=assignee_id)
    requested_status = input.status if input.status_provided else task.status
    if requested_status is None:
        raise CustomerTaskInvalidTransition(task.status, "")
    if (
        input.status_provided
        and requested_status != task.status
        and requested_status not in _ALLOWED_TRANSITIONS[task.status]
    ):
        raise CustomerTaskInvalidTransition(task.status, requested_status)

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
    if input.name_provided:
        task.name = cast(str, input.name)
    task.description = input.description if input.description_provided else task.description
    task.assigned_to = assignee
    task.due_at = input.due_at if input.due_at_provided else task.due_at
    task.status = requested_status
    task.completed_at = completed_at
    task.completed_by = completed_by
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
        before_tags=before_tags,
        after_tags=after_tags,
    )
    return _CustomerTaskWrite(
        task=task,
        before_assignee=before_assignee,
        tag_names=after_tags if after_tags != before_tags else None,
        activity=CustomerTaskActivity(
            team_id=team.id,
            task=task,
            actor=actor,
            activity_type=CustomerTaskActivityType.UPDATED,
            changes=changes,
        ),
    )


def _update_customer_task_access(*, team: Team, write: _CustomerTaskWrite, actor: User | None) -> None:
    _set_customer_task_assignee_access(
        task=write.task,
        organization_id=team.organization_id,
        before_assignee=write.before_assignee,
        after_assignee=write.task.assigned_to,
        actor=actor,
    )


def _bulk_update_customer_task_access(*, team: Team, writes: list[_CustomerTaskWrite], actor: User | None) -> None:
    assignment_changes = [write for write in writes if write.before_assignee != write.task.assigned_to]
    if not assignment_changes:
        return
    user_ids = {
        assignee.id
        for write in assignment_changes
        for assignee in (write.before_assignee, write.task.assigned_to)
        if assignee is not None
    }
    membership_ids = dict(
        OrganizationMembership.objects.filter(organization_id=team.organization_id, user_id__in=user_ids).values_list(
            "user_id", "id"
        )
    )
    inputs: list[access_control_contracts.SetObjectAccessControlInput] = []
    for write in assignment_changes:
        for assignee, access_level in ((write.before_assignee, None), (write.task.assigned_to, "editor")):
            if assignee is None:
                continue
            membership_id = membership_ids.get(assignee.id)
            if membership_id is None:
                if access_level is not None:
                    raise CustomerTaskAssigneeInvalid()
                continue
            inputs.append(
                access_control_contracts.SetObjectAccessControlInput(
                    resource="customer_task",
                    resource_id=str(write.task.id),
                    organization_member_id=membership_id,
                    access_level=access_level,
                    created_by_id=actor.id if actor is not None else None,
                )
            )
    try:
        access_control_api.bulk_set_object_access_controls(team_id=team.id, inputs=inputs)
    except access_control_api.InvalidObjectAccessControlError as error:
        raise CustomerTaskAssigneeInvalid() from error


def update_customer_task(
    *,
    team: Team,
    task_id: UUID | str,
    input: contracts.UpdateCustomerTaskInput,
    actor: User | None,
    user_access_control: UserAccessControl,
) -> CustomerTask | None:
    with transaction.atomic():
        task = _task_for_write(team_id=team.id, task_id=task_id, user_access_control=user_access_control)
        if task is None:
            return None
        write = _prepare_customer_task_update(
            team=team, task=task, input=input, actor=actor, user_access_control=user_access_control
        )
        if write is not None:
            task.save()
            if write.tag_names is not None:
                _set_customer_task_tags(team.id, [(task, write.tag_names)])
            _update_customer_task_access(team=team, write=write, actor=actor)
            write.activity.save()
        return task


def bulk_update_customer_tasks(
    *,
    team: Team,
    task_ids: list[UUID],
    input: contracts.UpdateCustomerTaskInput,
    archived: bool | None,
    actor: User | None,
    user_access_control: UserAccessControl,
) -> int | None:
    try:
        with transaction.atomic():
            tasks = list(
                _visible_task_queryset(team.id, user_access_control)
                .filter(id__in=task_ids)
                .order_by("id")
                .select_for_update(of=("self",))
            )
            if len(tasks) != len(task_ids):
                return None
            validation = _CustomerTaskBulkValidation(
                team=team, visible_tasks=tasks, input=input, user_access_control=user_access_control
            )
            writes: list[_CustomerTaskWrite] = []
            now = timezone.now()
            for task in tasks:
                if archived is None:
                    write = _prepare_customer_task_update(
                        team=team,
                        task=task,
                        input=input,
                        actor=actor,
                        user_access_control=user_access_control,
                        validation=validation,
                    )
                    if write is None:
                        continue
                else:
                    if not validation.can_edit(task):
                        raise CustomerTaskAccessDenied()
                    if (task.archived_at is not None) == archived:
                        continue
                    task.archived_at = now if archived else None
                    write = _CustomerTaskWrite(
                        task=task,
                        before_assignee=task.assigned_to,
                        activity=CustomerTaskActivity(
                            team_id=team.id,
                            task=task,
                            actor=actor,
                            activity_type=CustomerTaskActivityType.ARCHIVED
                            if archived
                            else CustomerTaskActivityType.RESTORED,
                            changes=[],
                        ),
                    )
                task.updated_at = now
                writes.append(write)
            CustomerTask.objects.for_team(team.id).bulk_update(
                [write.task for write in writes],
                [
                    "account",
                    "assigned_to",
                    "due_at",
                    "status",
                    "completed_at",
                    "completed_by",
                    "archived_at",
                    "updated_at",
                ],
            )
            _set_customer_task_tags(
                team.id, ((write.task, write.tag_names) for write in writes if write.tag_names is not None)
            )
            _bulk_update_customer_task_access(team=team, writes=writes, actor=actor)
            CustomerTaskActivity.objects.for_team(team.id).bulk_create([write.activity for write in writes])
            return len(writes)
    except IntegrityError as error:
        raise contracts.CustomerTaskBulkUpdateConflict() from error


def archive_customer_task(
    *, team_id: int, task_id: UUID | str, actor: User | None, user_access_control: UserAccessControl
) -> CustomerTask | None:
    with transaction.atomic():
        task = _task_for_write(team_id=team_id, task_id=task_id, user_access_control=user_access_control)
        if task is None:
            return None
        if not can_access_customer_task_object(task=task, user_access_control=user_access_control, write=True):
            raise CustomerTaskAccessDenied()
        if task.archived_at is None:
            task.archived_at = timezone.now()
            task.save(update_fields=["archived_at", "updated_at"])
            _record_activity(task=task, activity_type=CustomerTaskActivityType.ARCHIVED, actor=actor, changes=[])
        return task


def restore_customer_task(
    *, team_id: int, task_id: UUID | str, actor: User | None, user_access_control: UserAccessControl
) -> CustomerTask | None:
    with transaction.atomic():
        task = _task_for_write(team_id=team_id, task_id=task_id, user_access_control=user_access_control)
        if task is None:
            return None
        if not can_access_customer_task_object(task=task, user_access_control=user_access_control, write=True):
            raise CustomerTaskAccessDenied()
        if task.archived_at is not None:
            task.archived_at = None
            task.save(update_fields=["archived_at", "updated_at"])
            _record_activity(task=task, activity_type=CustomerTaskActivityType.RESTORED, actor=actor, changes=[])
        return task


def _list_visible_historical_account_ids(
    *,
    team_id: int,
    activities: list[CustomerTaskActivity],
    user_access_control: UserAccessControl,
) -> frozenset[str]:
    historical_account_ids: set[UUID] = set()
    for activity in activities:
        for change in activity.changes:
            if not isinstance(change, dict):
                continue
            for context_key in ("before_account_id", "after_account_id"):
                account_id = change.get(context_key)
                if not isinstance(account_id, str):
                    continue
                try:
                    historical_account_ids.add(UUID(account_id))
                except ValueError:
                    continue
            if change.get("field") != "account":
                continue
            for key in ("before", "after"):
                snapshot = change.get(key)
                if not isinstance(snapshot, dict) or not isinstance(snapshot.get("id"), str):
                    continue
                try:
                    historical_account_ids.add(UUID(snapshot["id"]))
                except ValueError:
                    continue
    if not historical_account_ids:
        return frozenset()
    visible_ids = _visible_account_queryset(team_id, user_access_control).filter(id__in=historical_account_ids)
    return frozenset(str(account_id) for account_id in visible_ids.values_list("id", flat=True))


def list_customer_task_activities(
    *, team_id: int, task_id: UUID | str, user_access_control: UserAccessControl, page: PageRequest
) -> _CustomerTaskActivityPage | None:
    task = get_customer_task(team_id=team_id, task_id=task_id, user_access_control=user_access_control)
    if task is None or not can_access_customer_task_object(
        task=task, user_access_control=user_access_control, write=False
    ):
        return None
    queryset = CustomerTaskActivity.objects.for_team(team_id).filter(task_id=task.id).select_related("actor")
    activities = select_page(queryset.order_by("-created_at", "-id"), page)
    visible_account_ids = _list_visible_historical_account_ids(
        team_id=team_id,
        activities=activities.results,
        user_access_control=user_access_control,
    )
    return _CustomerTaskActivityPage(activities=activities, visible_account_ids=visible_account_ids)


def can_access_customer_task_object(*, task: CustomerTask, user_access_control: UserAccessControl, write: bool) -> bool:
    if (
        task.account_id is not None
        and not _visible_account_queryset(task.team_id, user_access_control).filter(id=task.account_id).exists()
    ):
        return False
    return user_access_control.check_access_level_for_object(task, "editor" if write else "viewer")
