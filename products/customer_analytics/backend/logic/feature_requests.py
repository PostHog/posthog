from typing import TYPE_CHECKING
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import Case, IntegerField, Q, QuerySet, Value, When
from django.db.models.functions import Lower
from django.utils import timezone

from posthog.models import User

from products.customer_analytics.backend.facade import contracts
from products.customer_analytics.backend.models import (
    Account,
    FeatureRequest,
    FeatureRequestAccountLink,
    FeatureRequestHistory,
    FeatureRequestHistorySource,
    FeatureRequestPriority,
    FeatureRequestProductArea,
    FeatureRequestProductAreaLink,
)

if TYPE_CHECKING:
    from posthog.rbac.user_access_control import UserAccessControl


class FeatureRequestValidationError(ValueError):
    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.message = message


class FeatureRequestProductAreaConflictError(ValueError):
    pass


class FeatureRequestConflictError(ValueError):
    pass


def _to_product_area_view(product_area: FeatureRequestProductArea) -> contracts.FeatureRequestProductAreaView:
    return contracts.FeatureRequestProductAreaView(
        id=product_area.id,
        name=product_area.name,
        display_order=product_area.display_order,
        is_active=product_area.is_active,
        created_at=product_area.created_at,
        updated_at=product_area.updated_at,
    )


def _to_feature_request_view(feature_request: FeatureRequest) -> contracts.FeatureRequestView:
    account_link = next(iter(feature_request.account_links.all()))
    return contracts.FeatureRequestView(
        id=feature_request.id,
        title=feature_request.title,
        description=feature_request.description,
        request_status=feature_request.status,
        request_priority=feature_request.priority,
        is_archived=feature_request.archived_at is not None,
        archived_at=feature_request.archived_at,
        archived_by=feature_request.archived_by_id,
        version=feature_request.version,
        account=contracts.FeatureRequestAccountView(id=account_link.account.id, name=account_link.account.name),
        product_areas=[_to_product_area_view(area) for area in feature_request.product_areas.all()],
        created_by=feature_request.created_by_id,
        updated_by=feature_request.updated_by_id,
        created_at=feature_request.created_at,
        updated_at=feature_request.updated_at,
    )


def _feature_request_queryset(team_id: int, user_access_control: "UserAccessControl") -> QuerySet[FeatureRequest]:
    accessible_account_ids = user_access_control.filter_queryset_by_access_level(
        Account.objects.for_team(team_id)
    ).values("id")
    return (
        FeatureRequest.objects.for_team(team_id)
        .filter(account_links__account_id__in=accessible_account_ids)
        .prefetch_related("product_areas", "account_links__account")
        .distinct()
    )


def _apply_priority_ordering(queryset: QuerySet[FeatureRequest], ordering: str) -> QuerySet[FeatureRequest]:
    if ordering == "-priority":
        priority_order = Case(
            When(priority=FeatureRequestPriority.HIGH, then=Value(0)),
            When(priority=FeatureRequestPriority.MEDIUM, then=Value(1)),
            When(priority=FeatureRequestPriority.LOW, then=Value(2)),
            default=Value(3),
            output_field=IntegerField(),
        )
    else:
        priority_order = Case(
            When(priority=FeatureRequestPriority.LOW, then=Value(0)),
            When(priority=FeatureRequestPriority.MEDIUM, then=Value(1)),
            When(priority=FeatureRequestPriority.HIGH, then=Value(2)),
            default=Value(3),
            output_field=IntegerField(),
        )
    return queryset.alias(priority_order=priority_order).order_by("priority_order", "id")


def _apply_ordering(queryset: QuerySet[FeatureRequest], ordering: str) -> QuerySet[FeatureRequest]:
    if ordering in {"priority", "-priority"}:
        return _apply_priority_ordering(queryset, ordering)
    if ordering == "title":
        return queryset.order_by(Lower("title"), "id")
    if ordering == "-title":
        return queryset.order_by(Lower("title").desc(), "-id")
    direction = "-" if ordering.startswith("-") else ""
    field = ordering.removeprefix("-")
    if field == "updated_at":
        return queryset.order_by(ordering, f"{direction}created_at", f"{direction}id")
    return queryset.order_by(ordering, f"{direction}id")


def _apply_filters(
    queryset: QuerySet[FeatureRequest], filters: contracts.FeatureRequestListFilters
) -> QuerySet[FeatureRequest]:
    search = filters.search.strip()
    if search:
        queryset = queryset.filter(Q(title__icontains=search) | Q(description__icontains=search))
    if filters.statuses:
        queryset = queryset.filter(status__in=filters.statuses)
    if filters.priorities:
        include_unprioritized = "none" in filters.priorities
        selected_priorities = tuple(priority for priority in filters.priorities if priority != "none")
        priority_filter = Q(priority__in=selected_priorities)
        if include_unprioritized:
            priority_filter |= Q(priority__isnull=True)
        queryset = queryset.filter(priority_filter)
    if filters.product_area_ids:
        queryset = queryset.filter(product_area_links__product_area_id__in=filters.product_area_ids)
    if filters.account_ids:
        queryset = queryset.filter(account_links__account_id__in=filters.account_ids)
    if filters.archive_state == "active":
        queryset = queryset.filter(archived_at__isnull=True)
    elif filters.archive_state == "archived":
        queryset = queryset.filter(archived_at__isnull=False)
    return queryset.distinct()


def _get_accessible_feature_request_for_update(
    *, team_id: int, feature_request_id: UUID, user_access_control: "UserAccessControl"
) -> FeatureRequest | None:
    feature_request = FeatureRequest.objects.for_team(team_id).select_for_update().filter(id=feature_request_id).first()
    if feature_request is None:
        return None
    linked_account_ids = set(
        FeatureRequestAccountLink.objects.for_team(team_id)
        .filter(feature_request=feature_request)
        .values_list("account_id", flat=True)
    )
    accessible_account_ids = set(
        user_access_control.filter_queryset_by_access_level(Account.objects.for_team(team_id))
        .filter(id__in=linked_account_ids)
        .values_list("id", flat=True)
    )
    return feature_request if linked_account_ids == accessible_account_ids else None


def _get_accessible_account(*, team_id: int, account_id: UUID, user_access_control: "UserAccessControl") -> Account:
    account = (
        user_access_control.filter_queryset_by_access_level(Account.objects.for_team(team_id))
        .filter(id=account_id)
        .first()
    )
    if account is None:
        raise FeatureRequestValidationError("account_id", "Select an account you can access.")
    return account


def _get_valid_product_areas(
    *, team_id: int, feature_request: FeatureRequest, product_area_ids: tuple[UUID, ...]
) -> list[FeatureRequestProductArea]:
    if not product_area_ids:
        raise FeatureRequestValidationError("product_area_ids", "Select at least one product area.")
    unique_ids = tuple(dict.fromkeys(product_area_ids))
    product_areas = list(FeatureRequestProductArea.objects.for_team(team_id).filter(id__in=unique_ids))
    if len(product_areas) != len(unique_ids):
        raise FeatureRequestValidationError("product_area_ids", "Select product areas from this project.")
    current_ids = set(
        FeatureRequestProductAreaLink.objects.for_team(team_id)
        .filter(feature_request=feature_request)
        .values_list("product_area_id", flat=True)
    )
    if any(not area.is_active and area.id not in current_ids for area in product_areas):
        raise FeatureRequestValidationError("product_area_ids", "Select active product areas from this project.")
    return product_areas


def _account_snapshot(account: Account) -> dict[str, str]:
    return {"id": str(account.id), "name": account.name}


def _history_account_id(value: object) -> UUID | None:
    if not isinstance(value, dict) or not isinstance(value.get("id"), str):
        return None
    try:
        return UUID(value["id"])
    except ValueError:
        return None


def _redact_history_account(value: object, accessible_account_ids: set[UUID]) -> object:
    if value is None:
        return None
    account_id = _history_account_id(value)
    if account_id is not None and account_id in accessible_account_ids:
        return value
    return {"id": None, "name": "Restricted account"}


def _redact_inaccessible_history_accounts(
    changes: list[contracts.FeatureRequestHistoryChange], accessible_account_ids: set[UUID]
) -> list[contracts.FeatureRequestHistoryChange]:
    redacted_changes: list[contracts.FeatureRequestHistoryChange] = []
    for change in changes:
        if change["field"] == "account":
            redacted_changes.append(
                contracts.FeatureRequestHistoryChange(
                    field=change["field"],
                    before=_redact_history_account(change["before"], accessible_account_ids),
                    after=_redact_history_account(change["after"], accessible_account_ids),
                )
            )
        else:
            redacted_changes.append(change)
    return redacted_changes


def _product_area_snapshots(product_areas: list[FeatureRequestProductArea]) -> list[dict[str, str]]:
    return [
        {"id": str(area.id), "name": area.name}
        for area in sorted(product_areas, key=lambda area: (area.display_order, area.name.lower(), str(area.id)))
    ]


def _ensure_initial_history(
    feature_request: FeatureRequest,
    *,
    account: Account | None = None,
    product_areas: list[FeatureRequestProductArea] | None = None,
) -> None:
    if account is None:
        account = (
            FeatureRequestAccountLink.objects.for_team(feature_request.team_id)
            .select_related("account")
            .get(feature_request=feature_request)
            .account
        )
    if product_areas is None:
        product_areas = list(
            FeatureRequestProductArea.objects.for_team(feature_request.team_id).filter(
                request_links__feature_request=feature_request
            )
        )
    FeatureRequestHistory.objects.for_team(feature_request.team_id).get_or_create(
        team_id=feature_request.team_id,
        feature_request=feature_request,
        is_initial=True,
        defaults={
            "changes": [
                {"field": "status", "before": None, "after": feature_request.status},
                {"field": "priority", "before": None, "after": feature_request.priority},
                {"field": "account", "before": None, "after": _account_snapshot(account)},
                {
                    "field": "product_areas",
                    "before": [],
                    "after": _product_area_snapshots(product_areas),
                },
            ],
            "source": FeatureRequestHistorySource.MANUAL,
            "actor_id": feature_request.created_by_id,
            "changed_at": feature_request.created_at,
        },
    )


def _refresh_feature_request(
    *, team_id: int, feature_request_id: UUID, user_access_control: "UserAccessControl"
) -> contracts.FeatureRequestView:
    refreshed = _feature_request_queryset(team_id, user_access_control).filter(id=feature_request_id).first()
    if refreshed is None:
        raise FeatureRequestValidationError("feature_request_id", "This feature request is no longer available.")
    return _to_feature_request_view(refreshed)


def list_product_areas(
    team_id: int, *, include_inactive: bool = False
) -> list[contracts.FeatureRequestProductAreaView]:
    queryset = FeatureRequestProductArea.objects.for_team(team_id)
    if not include_inactive:
        queryset = queryset.filter(is_active=True)
    return [_to_product_area_view(area) for area in queryset.order_by("display_order", "name", "id")]


def create_product_area(
    *, team_id: int, name: str, display_order: int, actor_id: int
) -> contracts.FeatureRequestProductAreaView:
    normalized_name = name.strip()
    if not normalized_name:
        raise FeatureRequestValidationError("name", "Enter a product area name.")
    try:
        product_area = FeatureRequestProductArea.objects.for_team(team_id).create(
            team_id=team_id,
            name=normalized_name,
            display_order=display_order,
            created_by_id=actor_id,
            updated_by_id=actor_id,
        )
    except IntegrityError:
        raise FeatureRequestProductAreaConflictError("A product area with this name already exists.")
    return _to_product_area_view(product_area)


def update_product_area(
    *,
    team_id: int,
    product_area_id: UUID,
    name: str | None,
    display_order: int | None,
    is_active: bool | None,
    actor_id: int,
) -> contracts.FeatureRequestProductAreaView | None:
    product_area = FeatureRequestProductArea.objects.for_team(team_id).filter(id=product_area_id).first()
    if product_area is None:
        return None
    if name is not None:
        normalized_name = name.strip()
        if not normalized_name:
            raise FeatureRequestValidationError("name", "Enter a product area name.")
        product_area.name = normalized_name
    if display_order is not None:
        product_area.display_order = display_order
    if is_active is not None:
        product_area.is_active = is_active
    product_area.updated_by_id = actor_id
    try:
        product_area.save()
    except IntegrityError:
        raise FeatureRequestProductAreaConflictError("A product area with this name already exists.")
    return _to_product_area_view(product_area)


def list_feature_requests(
    *,
    team_id: int,
    user_access_control: "UserAccessControl",
    filters: contracts.FeatureRequestListFilters,
    offset: int,
    limit: int,
) -> tuple[list[contracts.FeatureRequestView], int]:
    queryset = _apply_filters(_feature_request_queryset(team_id, user_access_control), filters)
    queryset = _apply_ordering(queryset, filters.ordering)
    total_count = queryset.count()
    return [_to_feature_request_view(item) for item in queryset[offset : offset + limit]], total_count


def get_feature_request(
    *, team_id: int, feature_request_id: UUID, user_access_control: "UserAccessControl"
) -> contracts.FeatureRequestView | None:
    feature_request = _feature_request_queryset(team_id, user_access_control).filter(id=feature_request_id).first()
    return _to_feature_request_view(feature_request) if feature_request is not None else None


def create_feature_request(
    *,
    team_id: int,
    input: contracts.CreateFeatureRequestInput,
    actor_id: int,
    user_access_control: "UserAccessControl",
) -> contracts.FeatureRequestCreateOutcome:
    title = input.title.strip()
    description = input.description.strip()
    if not title:
        raise FeatureRequestValidationError("title", "Enter a title.")
    if not input.product_area_ids:
        raise FeatureRequestValidationError("product_area_ids", "Select at least one product area.")

    existing = FeatureRequest.objects.for_team(team_id).filter(idempotency_key=input.idempotency_key).first()
    if existing is not None:
        accessible_existing = _feature_request_queryset(team_id, user_access_control).filter(id=existing.id).first()
        if accessible_existing is None:
            raise FeatureRequestValidationError("idempotency_key", "This idempotency key is already in use.")
        return contracts.FeatureRequestCreateOutcome(
            request=_to_feature_request_view(accessible_existing),
            created=False,
        )

    accessible_account = _get_accessible_account(
        team_id=team_id,
        account_id=input.account_id,
        user_access_control=user_access_control,
    )
    unique_product_area_ids = tuple(dict.fromkeys(input.product_area_ids))
    product_areas = list(
        FeatureRequestProductArea.objects.for_team(team_id).filter(
            id__in=unique_product_area_ids,
            is_active=True,
        )
    )
    if len(product_areas) != len(unique_product_area_ids):
        raise FeatureRequestValidationError("product_area_ids", "Select active product areas from this project.")

    with transaction.atomic():
        feature_request, created = FeatureRequest.objects.for_team(team_id).get_or_create(
            team_id=team_id,
            idempotency_key=input.idempotency_key,
            defaults={
                "title": title,
                "description": description,
                "created_by_id": actor_id,
                "updated_by_id": actor_id,
            },
        )
        if created:
            FeatureRequestAccountLink.objects.for_team(team_id).create(
                team_id=team_id,
                feature_request=feature_request,
                account=accessible_account,
            )
            FeatureRequestProductAreaLink.objects.for_team(team_id).bulk_create(
                [
                    FeatureRequestProductAreaLink(
                        team_id=team_id,
                        feature_request=feature_request,
                        product_area=product_area,
                    )
                    for product_area in product_areas
                ]
            )
            _ensure_initial_history(
                feature_request,
                account=accessible_account,
                product_areas=product_areas,
            )

    return contracts.FeatureRequestCreateOutcome(
        request=_refresh_feature_request(
            team_id=team_id,
            feature_request_id=feature_request.id,
            user_access_control=user_access_control,
        ),
        created=created,
    )


def update_feature_request(
    *,
    team_id: int,
    feature_request_id: UUID,
    input: contracts.UpdateFeatureRequestInput,
    actor_id: int,
    user_access_control: "UserAccessControl",
) -> contracts.FeatureRequestView | None:
    with transaction.atomic():
        feature_request = _get_accessible_feature_request_for_update(
            team_id=team_id,
            feature_request_id=feature_request_id,
            user_access_control=user_access_control,
        )
        if feature_request is None:
            return None
        if feature_request.archived_at is not None:
            raise FeatureRequestValidationError("feature_request", "Restore this request before editing it.")
        if feature_request.version != input.expected_version:
            raise FeatureRequestConflictError("This request changed since you opened it. Reload it and try again.")
        _ensure_initial_history(feature_request)

        update_fields: set[str] = set()
        history_changes: list[contracts.FeatureRequestHistoryChange] = []
        if input.title is not None:
            title = input.title.strip()
            if not title:
                raise FeatureRequestValidationError("title", "Enter a title.")
            if title != feature_request.title:
                feature_request.title = title
                update_fields.add("title")
        if input.description is not None:
            description = input.description.strip()
            if description != feature_request.description:
                feature_request.description = description
                update_fields.add("description")
        if input.request_status is not None and input.request_status != feature_request.status:
            history_changes.append({"field": "status", "before": feature_request.status, "after": input.request_status})
            feature_request.status = input.request_status
            update_fields.add("status")
        if input.request_priority_is_set and input.request_priority != feature_request.priority:
            history_changes.append(
                {"field": "priority", "before": feature_request.priority, "after": input.request_priority}
            )
            feature_request.priority = input.request_priority
            update_fields.add("priority")

        relations_changed = False
        if input.account_id is not None:
            account = _get_accessible_account(
                team_id=team_id,
                account_id=input.account_id,
                user_access_control=user_access_control,
            )
            account_link = (
                FeatureRequestAccountLink.objects.for_team(team_id)
                .select_related("account")
                .get(feature_request=feature_request)
            )
            if account_link.account_id != account.id:
                history_changes.append(
                    {
                        "field": "account",
                        "before": _account_snapshot(account_link.account),
                        "after": _account_snapshot(account),
                    }
                )
                account_link.account = account
                account_link.save(update_fields=["account"])
                relations_changed = True

        if input.product_area_ids is not None:
            product_areas = _get_valid_product_areas(
                team_id=team_id,
                feature_request=feature_request,
                product_area_ids=input.product_area_ids,
            )
            requested_ids = {area.id for area in product_areas}
            existing_links = list(
                FeatureRequestProductAreaLink.objects.for_team(team_id)
                .filter(feature_request=feature_request)
                .select_related("product_area")
            )
            existing_ids = {link.product_area_id for link in existing_links}
            if requested_ids != existing_ids:
                history_changes.append(
                    {
                        "field": "product_areas",
                        "before": _product_area_snapshots([link.product_area for link in existing_links]),
                        "after": _product_area_snapshots(product_areas),
                    }
                )
                FeatureRequestProductAreaLink.objects.for_team(team_id).filter(
                    feature_request=feature_request,
                    product_area_id__in=existing_ids - requested_ids,
                ).delete()
                FeatureRequestProductAreaLink.objects.for_team(team_id).bulk_create(
                    [
                        FeatureRequestProductAreaLink(
                            team_id=team_id,
                            feature_request=feature_request,
                            product_area=area,
                        )
                        for area in product_areas
                        if area.id not in existing_ids
                    ]
                )
                relations_changed = True

        if update_fields or relations_changed:
            changed_at = timezone.now()
            feature_request.updated_by_id = actor_id
            feature_request.updated_at = changed_at
            feature_request.version += 1
            update_fields.update({"updated_by_id", "updated_at", "version"})
            feature_request.save(update_fields=update_fields)
            if history_changes:
                FeatureRequestHistory.objects.for_team(team_id).create(
                    team_id=team_id,
                    feature_request=feature_request,
                    changes=history_changes,
                    source=FeatureRequestHistorySource.MANUAL,
                    actor_id=actor_id,
                    changed_at=changed_at,
                )

    return _refresh_feature_request(
        team_id=team_id,
        feature_request_id=feature_request_id,
        user_access_control=user_access_control,
    )


def set_feature_request_archived(
    *,
    team_id: int,
    feature_request_id: UUID,
    expected_version: int,
    archived: bool,
    actor_id: int,
    user_access_control: "UserAccessControl",
) -> contracts.FeatureRequestView | None:
    with transaction.atomic():
        feature_request = _get_accessible_feature_request_for_update(
            team_id=team_id,
            feature_request_id=feature_request_id,
            user_access_control=user_access_control,
        )
        if feature_request is None:
            return None
        if feature_request.version != expected_version:
            raise FeatureRequestConflictError("This request changed since you opened it. Reload it and try again.")
        is_archived = feature_request.archived_at is not None
        if archived != is_archived:
            changed_at = timezone.now()
            feature_request.archived_at = changed_at if archived else None
            feature_request.archived_by_id = actor_id if archived else None
            feature_request.updated_by_id = actor_id
            feature_request.updated_at = changed_at
            feature_request.version += 1
            feature_request.save(
                update_fields=["archived_at", "archived_by_id", "updated_by_id", "updated_at", "version"]
            )

    return _refresh_feature_request(
        team_id=team_id,
        feature_request_id=feature_request_id,
        user_access_control=user_access_control,
    )


def list_feature_request_history(
    *, team_id: int, feature_request_id: UUID, user_access_control: "UserAccessControl"
) -> list[contracts.FeatureRequestHistoryView] | None:
    if not _feature_request_queryset(team_id, user_access_control).filter(id=feature_request_id).exists():
        return None
    history = list(
        FeatureRequestHistory.objects.for_team(team_id)
        .filter(feature_request_id=feature_request_id)
        .order_by("-changed_at", "-id")
    )
    history_account_ids: set[UUID] = set()
    for entry in history:
        for change in entry.changes:
            if change.get("field") != "account":
                continue
            for value in (change.get("before"), change.get("after")):
                account_id = _history_account_id(value)
                if account_id is not None:
                    history_account_ids.add(account_id)
    accessible_account_ids = set(
        user_access_control.filter_queryset_by_access_level(Account.objects.for_team(team_id))
        .filter(id__in=history_account_ids)
        .values_list("id", flat=True)
    )
    actors = User.objects.filter(id__in={entry.actor_id for entry in history if entry.actor_id is not None})
    actor_names = {actor.id: actor.get_full_name().strip() or actor.email for actor in actors}
    return [
        contracts.FeatureRequestHistoryView(
            id=entry.id,
            changes=_redact_inaccessible_history_accounts(entry.changes, accessible_account_ids),
            is_initial=entry.is_initial,
            change_source=entry.source,
            actor_id=entry.actor_id,
            actor_name=actor_names.get(entry.actor_id),
            changed_at=entry.changed_at,
        )
        for entry in history
    ]


def list_feature_request_status_history(
    *, team_id: int, feature_request_id: UUID, user_access_control: "UserAccessControl"
) -> list[contracts.FeatureRequestStatusHistoryView] | None:
    history = list_feature_request_history(
        team_id=team_id,
        feature_request_id=feature_request_id,
        user_access_control=user_access_control,
    )
    if history is None:
        return None
    status_history: list[contracts.FeatureRequestStatusHistoryView] = []
    for entry in history:
        status_change = next((change for change in entry.changes if change.get("field") == "status"), None)
        if status_change is None:
            continue
        request_status = status_change.get("after")
        if not isinstance(request_status, str):
            continue
        previous_status = status_change.get("before")
        status_history.append(
            contracts.FeatureRequestStatusHistoryView(
                id=entry.id,
                previous_status=previous_status if isinstance(previous_status, str) else None,
                request_status=request_status,
                change_source=entry.change_source,
                actor_id=entry.actor_id,
                actor_name=entry.actor_name,
                changed_at=entry.changed_at,
            )
        )
    return status_history
