from typing import TYPE_CHECKING, Protocol, cast
from urllib.parse import urlparse
from uuid import UUID

from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import Case, Count, IntegerField, Prefetch, Q, QuerySet, Value, When
from django.db.models.functions import Lower
from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.models import UploadedMedia, User

from products.customer_analytics.backend.facade import contracts
from products.customer_analytics.backend.models import (
    Account,
    FeatureRequest,
    FeatureRequestAccountLink,
    FeatureRequestEvidence,
    FeatureRequestHistory,
    FeatureRequestHistorySource,
    FeatureRequestPriority,
    FeatureRequestProductArea,
    FeatureRequestProductAreaLink,
)

if TYPE_CHECKING:
    from posthog.rbac.user_access_control import UserAccessControl


class _FeatureRequestWithPermissionLinks(Protocol):
    _permission_account_links: list[FeatureRequestAccountLink]


class FeatureRequestValidationError(ValueError):
    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.message = message


class FeatureRequestProductAreaConflictError(ValueError):
    pass


class FeatureRequestConflictError(ValueError):
    pass


@frozen
class _ValidatedEvidence:
    summary: str
    customer_quote: str
    source: str
    source_url: str
    image_ids: tuple[UUID, ...]


def _to_product_area_view(product_area: FeatureRequestProductArea) -> contracts.FeatureRequestProductAreaView:
    return contracts.FeatureRequestProductAreaView(
        id=product_area.id,
        name=product_area.name,
        display_order=product_area.display_order,
        is_active=product_area.is_active,
        created_at=product_area.created_at,
        updated_at=product_area.updated_at,
    )


def _to_evidence_view(evidence: FeatureRequestEvidence) -> contracts.FeatureRequestEvidenceView:
    return contracts.FeatureRequestEvidenceView(
        id=evidence.id,
        summary=evidence.summary,
        customer_quote=evidence.customer_quote,
        evidence_source=evidence.source,
        source_url=evidence.source_url,
        requested_on=evidence.requested_on,
        image_ids=list(evidence.image_ids),
        created_by=evidence.created_by_id,
        updated_by=evidence.updated_by_id,
        created_at=evidence.created_at,
        updated_at=evidence.updated_at,
    )


def _to_account_link_view(
    account_link: FeatureRequestAccountLink, *, include_evidence: bool
) -> contracts.FeatureRequestAccountLinkView:
    evidence = [_to_evidence_view(item) for item in account_link.evidence.all()] if include_evidence else []
    evidence_count = getattr(account_link, "evidence_count", len(evidence))
    return contracts.FeatureRequestAccountLinkView(
        id=account_link.id,
        account=contracts.FeatureRequestAccountView(id=account_link.account.id, name=account_link.account.name),
        evidence=evidence,
        evidence_count=evidence_count,
        created_at=account_link.created_at,
        updated_at=account_link.updated_at,
    )


def _get_feature_request_can_update(feature_request: FeatureRequest, user_access_control: "UserAccessControl") -> bool:
    account_links = cast(_FeatureRequestWithPermissionLinks, feature_request)._permission_account_links
    return (
        user_access_control.check_access_level_for_resource("customer_analytics", required_level="editor")
        and bool(account_links)
        and all(
            user_access_control.check_access_level_for_object(link.account, required_level="editor")
            for link in account_links
        )
    )


def _to_feature_request_view(
    feature_request: FeatureRequest,
    *,
    user_access_control: "UserAccessControl",
    include_evidence: bool = True,
) -> contracts.FeatureRequestView:
    account_links = [
        _to_account_link_view(link, include_evidence=include_evidence) for link in feature_request.account_links.all()
    ]
    legacy_account = account_links[0].account if account_links else None
    account_links.sort(
        key=lambda link: (
            -link.evidence_count,
            link.account.name.casefold() if link.account else "",
            str(link.id),
        )
    )
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
        can_update=_get_feature_request_can_update(feature_request, user_access_control),
        account=legacy_account,
        account_links=account_links,
        product_areas=[_to_product_area_view(area) for area in feature_request.product_areas.all()],
        created_by=feature_request.created_by_id,
        updated_by=feature_request.updated_by_id,
        created_at=feature_request.created_at,
        updated_at=feature_request.updated_at,
    )


def _feature_request_queryset(
    team_id: int,
    user_access_control: "UserAccessControl",
    *,
    include_evidence: bool = True,
) -> QuerySet[FeatureRequest]:
    accessible_account_ids = user_access_control.filter_queryset_by_access_level(
        Account.objects.for_team(team_id)
    ).values("id")
    visible_links = (
        FeatureRequestAccountLink.objects.for_team(team_id)
        .filter(account_id__in=accessible_account_ids, unlinked_at__isnull=True)
        .select_related("account")
        .annotate(evidence_count=Count("evidence"))
        .order_by("account__name", "id")
    )
    if include_evidence:
        visible_links = visible_links.prefetch_related("evidence")
    permission_links = (
        FeatureRequestAccountLink.objects.for_team(team_id).filter(unlinked_at__isnull=True).select_related("account")
    )
    queryset = (
        FeatureRequest.objects.for_team(team_id)
        .filter(account_links__account_id__in=accessible_account_ids, account_links__unlinked_at__isnull=True)
        .prefetch_related("product_areas", Prefetch("account_links", queryset=visible_links))
    )
    return queryset.prefetch_related(
        Prefetch("account_links", queryset=permission_links, to_attr="_permission_account_links")
    ).distinct()


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
    queryset: QuerySet[FeatureRequest],
    filters: contracts.FeatureRequestListFilters,
    account_filter_ids: tuple[UUID, ...],
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
        queryset = queryset.filter(
            account_links__account_id__in=account_filter_ids,
            account_links__unlinked_at__isnull=True,
        )
    if filters.created_by_ids:
        queryset = queryset.filter(created_by_id__in=filters.created_by_ids)
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
    account_links = list(
        FeatureRequestAccountLink.objects.for_team(team_id)
        .filter(feature_request=feature_request, unlinked_at__isnull=True)
        .select_related("account")
    )
    linked_account_ids = {link.account_id for link in account_links}
    accessible_account_ids = set(
        user_access_control.filter_queryset_by_access_level(Account.objects.for_team(team_id))
        .filter(id__in=linked_account_ids)
        .values_list("id", flat=True)
    )
    if linked_account_ids != accessible_account_ids:
        return None
    if any(
        not user_access_control.check_access_level_for_object(link.account, required_level="editor")
        for link in account_links
    ):
        raise PermissionDenied
    return feature_request


def _get_accessible_account(*, team_id: int, account_id: UUID, user_access_control: "UserAccessControl") -> Account:
    account = (
        user_access_control.filter_queryset_by_access_level(Account.objects.for_team(team_id))
        .filter(id=account_id)
        .first()
    )
    if account is None:
        raise FeatureRequestValidationError("account_id", "Select an account you can access.")
    if not user_access_control.check_access_level_for_object(account, required_level="editor"):
        raise PermissionDenied
    return account


def _get_accessible_accounts(
    *, team_id: int, account_ids: tuple[UUID, ...], user_access_control: "UserAccessControl"
) -> list[Account]:
    unique_ids = tuple(dict.fromkeys(account_ids))
    if not unique_ids:
        raise FeatureRequestValidationError("account_ids", "Select at least one account.")
    accounts = list(
        user_access_control.filter_queryset_by_access_level(Account.objects.for_team(team_id)).filter(id__in=unique_ids)
    )
    if len(accounts) != len(unique_ids):
        raise FeatureRequestValidationError("account_ids", "Select accounts you can access.")
    if any(
        not user_access_control.check_access_level_for_object(account, required_level="editor") for account in accounts
    ):
        raise PermissionDenied
    return accounts


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


def _account_snapshots(accounts: list[Account]) -> list[dict[str, str]]:
    return [
        _account_snapshot(account)
        for account in sorted(accounts, key=lambda account: (account.name.lower(), str(account.id)))
    ]


def _evidence_snapshot(evidence: FeatureRequestEvidence, *, account: Account | None = None) -> dict[str, object]:
    evidence_account = account or evidence.account_link.account
    return {
        "id": str(evidence.id),
        "account": _account_snapshot(evidence_account),
        "summary": evidence.summary,
        "customer_quote": evidence.customer_quote,
        "source": evidence.source,
        "source_url": evidence.source_url,
        "requested_on": evidence.requested_on.isoformat() if evidence.requested_on else None,
        "image_ids": [str(image_id) for image_id in evidence.image_ids],
    }


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


def _filter_history_accounts(value: object, accessible_account_ids: set[UUID]) -> object:
    if not isinstance(value, list):
        return []
    return [item for item in value if _history_account_id(item) in accessible_account_ids]


def _evidence_history_account_id(value: object) -> UUID | None:
    if not isinstance(value, dict):
        return None
    return _history_account_id(value.get("account"))


def _redact_inaccessible_history_accounts(
    changes: list[contracts.FeatureRequestHistoryChange], accessible_account_ids: set[UUID]
) -> list[contracts.FeatureRequestHistoryChange]:
    visible_changes: list[contracts.FeatureRequestHistoryChange] = []
    for change in changes:
        if change["field"] == "account":
            visible_changes.append(
                contracts.FeatureRequestHistoryChange(
                    field=change["field"],
                    before=_redact_history_account(change["before"], accessible_account_ids),
                    after=_redact_history_account(change["after"], accessible_account_ids),
                )
            )
        elif change["field"] == "accounts":
            before = _filter_history_accounts(change["before"], accessible_account_ids)
            after = _filter_history_accounts(change["after"], accessible_account_ids)
            if before != after:
                visible_changes.append(
                    contracts.FeatureRequestHistoryChange(
                        field=change["field"],
                        before=before,
                        after=after,
                    )
                )
        elif change["field"] == "evidence":
            account_id = _evidence_history_account_id(change["after"]) or _evidence_history_account_id(change["before"])
            if account_id in accessible_account_ids:
                visible_changes.append(change)
        else:
            visible_changes.append(change)
    return visible_changes


def _product_area_snapshots(product_areas: list[FeatureRequestProductArea]) -> list[dict[str, str]]:
    return [
        {"id": str(area.id), "name": area.name}
        for area in sorted(product_areas, key=lambda area: (area.display_order, area.name.lower(), str(area.id)))
    ]


def _ensure_initial_history(
    feature_request: FeatureRequest,
    *,
    accounts: list[Account] | None = None,
    product_areas: list[FeatureRequestProductArea] | None = None,
    evidence: FeatureRequestEvidence | None = None,
) -> None:
    if accounts is None:
        accounts = list(
            Account.objects.for_team(feature_request.team_id).filter(
                feature_request_links__feature_request=feature_request,
                feature_request_links__unlinked_at__isnull=True,
            )
        )
    if product_areas is None:
        product_areas = list(
            FeatureRequestProductArea.objects.for_team(feature_request.team_id).filter(
                request_links__feature_request=feature_request
            )
        )
    changes: list[contracts.FeatureRequestHistoryChange] = [
        {"field": "status", "before": None, "after": feature_request.status},
        {"field": "priority", "before": None, "after": feature_request.priority},
        {"field": "accounts", "before": [], "after": _account_snapshots(accounts)},
        {
            "field": "product_areas",
            "before": [],
            "after": _product_area_snapshots(product_areas),
        },
    ]
    if evidence is not None:
        changes.append(
            {
                "field": "evidence",
                "before": None,
                "after": _evidence_snapshot(evidence),
            }
        )
    FeatureRequestHistory.objects.for_team(feature_request.team_id).get_or_create(
        team_id=feature_request.team_id,
        feature_request=feature_request,
        is_initial=True,
        defaults={
            "changes": changes,
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
    return _to_feature_request_view(refreshed, user_access_control=user_access_control)


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
    account_filter_ids: tuple[UUID, ...] = ()
    if filters.account_ids:
        account_filter_ids = tuple(
            user_access_control.filter_queryset_by_access_level(Account.objects.for_team(team_id))
            .filter(id__in=filters.account_ids)
            .values_list("id", flat=True)
        )
    queryset = _apply_filters(
        _feature_request_queryset(team_id, user_access_control, include_evidence=False),
        filters,
        account_filter_ids,
    )
    queryset = _apply_ordering(queryset, filters.ordering)
    total_count = queryset.count()
    return [
        _to_feature_request_view(item, user_access_control=user_access_control, include_evidence=False)
        for item in queryset[offset : offset + limit]
    ], total_count


def get_feature_request(
    *, team_id: int, feature_request_id: UUID, user_access_control: "UserAccessControl"
) -> contracts.FeatureRequestView | None:
    feature_request = _feature_request_queryset(team_id, user_access_control).filter(id=feature_request_id).first()
    return (
        _to_feature_request_view(feature_request, user_access_control=user_access_control)
        if feature_request is not None
        else None
    )


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

    evidence_input = input.evidence
    validated_evidence = (
        _validate_evidence(team_id=team_id, input=evidence_input) if evidence_input is not None else None
    )
    existing = FeatureRequest.objects.for_team(team_id).filter(idempotency_key=input.idempotency_key).first()
    if existing is not None:
        accessible_existing = _feature_request_queryset(team_id, user_access_control).filter(id=existing.id).first()
        if accessible_existing is None:
            raise FeatureRequestValidationError("idempotency_key", "This idempotency key is already in use.")
        return contracts.FeatureRequestCreateOutcome(
            request=_to_feature_request_view(accessible_existing, user_access_control=user_access_control),
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
            account_link = FeatureRequestAccountLink.objects.for_team(team_id).create(
                team_id=team_id,
                feature_request=feature_request,
                account=accessible_account,
            )
            initial_evidence = None
            if validated_evidence is not None and evidence_input is not None:
                initial_evidence = FeatureRequestEvidence.objects.for_team(team_id).create(
                    team_id=team_id,
                    account_link=account_link,
                    summary=validated_evidence.summary,
                    customer_quote=validated_evidence.customer_quote,
                    source=validated_evidence.source,
                    source_url=validated_evidence.source_url,
                    requested_on=evidence_input.requested_on,
                    image_ids=list(validated_evidence.image_ids),
                    created_by_id=actor_id,
                    updated_by_id=actor_id,
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
                accounts=[accessible_account],
                product_areas=product_areas,
                evidence=initial_evidence,
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
        if input.account_ids is not None:
            accounts = _get_accessible_accounts(
                team_id=team_id,
                account_ids=input.account_ids,
                user_access_control=user_access_control,
            )
            requested_ids = {account.id for account in accounts}
            active_links = list(
                FeatureRequestAccountLink.objects.for_team(team_id)
                .filter(feature_request=feature_request, unlinked_at__isnull=True)
                .select_related("account")
            )
            active_ids = {link.account_id for link in active_links}
            if requested_ids != active_ids:
                changed_at = timezone.now()
                history_changes.append(
                    {
                        "field": "accounts",
                        "before": _account_snapshots([link.account for link in active_links]),
                        "after": _account_snapshots(accounts),
                    }
                )
                FeatureRequestAccountLink.objects.for_team(team_id).filter(
                    feature_request=feature_request,
                    account_id__in=active_ids - requested_ids,
                ).update(unlinked_at=changed_at, unlinked_by_id=actor_id, updated_at=changed_at)
                for account in accounts:
                    link, created = FeatureRequestAccountLink.objects.for_team(team_id).get_or_create(
                        team_id=team_id,
                        feature_request=feature_request,
                        account=account,
                    )
                    if not created and link.unlinked_at is not None:
                        link.unlinked_at = None
                        link.unlinked_by_id = None
                        link.updated_at = changed_at
                        link.save(update_fields=["unlinked_at", "unlinked_by_id", "updated_at"])
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


def _validate_image_ids(*, team_id: int, image_ids: tuple[UUID, ...]) -> tuple[UUID, ...]:
    unique_image_ids = tuple(dict.fromkeys(image_ids))
    valid_image_ids = set(
        UploadedMedia.objects.filter(
            team_id=team_id,
            id__in=unique_image_ids,
            content_type__startswith="image/",
            media_location__isnull=False,
        ).values_list("id", flat=True)
    )
    if len(valid_image_ids) != len(unique_image_ids):
        raise FeatureRequestValidationError("image_ids", "Select images uploaded to this project.")
    return unique_image_ids


def _validate_evidence(
    *,
    team_id: int,
    input: (
        contracts.FeatureRequestEvidenceInput
        | contracts.CreateFeatureRequestEvidenceInput
        | contracts.UpdateFeatureRequestEvidenceInput
    ),
    current_image_ids: tuple[UUID, ...] = (),
) -> _ValidatedEvidence:
    summary = input.summary.strip()
    customer_quote = input.customer_quote.strip()
    source_url = input.source_url.strip()
    requested_image_ids = input.image_ids
    image_ids = (
        current_image_ids
        if requested_image_ids is None
        else _validate_image_ids(team_id=team_id, image_ids=requested_image_ids)
    )
    if (
        not summary
        and not customer_quote
        and not source_url
        and not image_ids
        and input.requested_on is None
        and input.evidence_source == "conversation"
    ):
        raise FeatureRequestValidationError(
            "evidence", "Enter a summary, customer quote, source URL, image, request date, or change the source."
        )
    if source_url:
        parsed_url = urlparse(source_url)
        if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            raise FeatureRequestValidationError("source_url", "Enter a valid HTTP or HTTPS URL.")
    if input.requested_on is not None and input.requested_on > timezone.localdate():
        raise FeatureRequestValidationError("requested_on", "The request date cannot be in the future.")
    return _ValidatedEvidence(
        summary=summary,
        customer_quote=customer_quote,
        source=input.evidence_source,
        source_url=source_url,
        image_ids=image_ids,
    )


def _get_evidence_account_link(
    *,
    team_id: int,
    feature_request_id: UUID,
    account_link_id: UUID,
    expected_version: int,
    user_access_control: "UserAccessControl",
) -> tuple[FeatureRequest, FeatureRequestAccountLink] | None:
    feature_request = FeatureRequest.objects.for_team(team_id).select_for_update().filter(id=feature_request_id).first()
    if feature_request is None:
        return None
    account_link = (
        FeatureRequestAccountLink.objects.for_team(team_id)
        .select_related("account")
        .filter(
            id=account_link_id,
            feature_request=feature_request,
            unlinked_at__isnull=True,
        )
        .first()
    )
    if account_link is None:
        return None
    _get_accessible_account(
        team_id=team_id,
        account_id=account_link.account_id,
        user_access_control=user_access_control,
    )
    if feature_request.archived_at is not None:
        raise FeatureRequestValidationError("feature_request", "Restore this request before editing evidence.")
    if feature_request.version != expected_version:
        raise FeatureRequestConflictError("This request changed since you opened it. Reload it and try again.")
    return feature_request, account_link


def _record_feature_request_changes(
    *,
    feature_request: FeatureRequest,
    changes: list[contracts.FeatureRequestHistoryChange],
    actor_id: int,
) -> None:
    changed_at = timezone.now()
    feature_request.version += 1
    feature_request.updated_by_id = actor_id
    feature_request.updated_at = changed_at
    feature_request.save(update_fields=["version", "updated_by_id", "updated_at"])
    FeatureRequestHistory.objects.for_team(feature_request.team_id).create(
        team_id=feature_request.team_id,
        feature_request=feature_request,
        changes=changes,
        source=FeatureRequestHistorySource.MANUAL,
        actor_id=actor_id,
        changed_at=changed_at,
    )


def _record_evidence_change(
    *,
    feature_request: FeatureRequest,
    before: dict[str, object] | None,
    after: dict[str, object] | None,
    actor_id: int,
) -> None:
    _record_feature_request_changes(
        feature_request=feature_request,
        changes=[{"field": "evidence", "before": before, "after": after}],
        actor_id=actor_id,
    )


def add_feature_request_account(
    *,
    team_id: int,
    feature_request_id: UUID,
    input: contracts.AddFeatureRequestAccountInput,
    actor_id: int,
    user_access_control: "UserAccessControl",
) -> contracts.FeatureRequestView | None:
    evidence_input = input.evidence
    validated_evidence = (
        _validate_evidence(team_id=team_id, input=evidence_input) if evidence_input is not None else None
    )
    with transaction.atomic():
        feature_request = _get_accessible_feature_request_for_update(
            team_id=team_id,
            feature_request_id=feature_request_id,
            user_access_control=user_access_control,
        )
        if feature_request is None:
            return None
        if feature_request.archived_at is not None:
            raise FeatureRequestValidationError("feature_request", "Restore this request before adding an account.")
        if feature_request.version != input.expected_version:
            raise FeatureRequestConflictError("This request changed since you opened it. Reload it and try again.")

        account = _get_accessible_account(
            team_id=team_id,
            account_id=input.account_id,
            user_access_control=user_access_control,
        )
        active_links = list(
            FeatureRequestAccountLink.objects.for_team(team_id)
            .filter(feature_request=feature_request, unlinked_at__isnull=True)
            .select_related("account")
        )
        if any(link.account_id == account.id for link in active_links):
            raise FeatureRequestValidationError("account_id", "This account is already linked to the request.")

        _ensure_initial_history(feature_request)
        changed_at = timezone.now()
        account_link, created = FeatureRequestAccountLink.objects.for_team(team_id).get_or_create(
            team_id=team_id,
            feature_request=feature_request,
            account=account,
        )
        if not created:
            account_link.unlinked_at = None
            account_link.unlinked_by_id = None
            account_link.updated_at = changed_at
            account_link.save(update_fields=["unlinked_at", "unlinked_by_id", "updated_at"])

        history_changes: list[contracts.FeatureRequestHistoryChange] = [
            {
                "field": "accounts",
                "before": _account_snapshots([link.account for link in active_links]),
                "after": _account_snapshots([link.account for link in active_links] + [account]),
            }
        ]
        if validated_evidence is not None and evidence_input is not None:
            evidence = FeatureRequestEvidence.objects.for_team(team_id).create(
                team_id=team_id,
                account_link=account_link,
                summary=validated_evidence.summary,
                customer_quote=validated_evidence.customer_quote,
                source=validated_evidence.source,
                source_url=validated_evidence.source_url,
                requested_on=evidence_input.requested_on,
                image_ids=list(validated_evidence.image_ids),
                created_by_id=actor_id,
                updated_by_id=actor_id,
            )
            history_changes.append(
                {
                    "field": "evidence",
                    "before": None,
                    "after": _evidence_snapshot(evidence, account=account),
                }
            )
        _record_feature_request_changes(
            feature_request=feature_request,
            changes=history_changes,
            actor_id=actor_id,
        )

    return _refresh_feature_request(
        team_id=team_id,
        feature_request_id=feature_request_id,
        user_access_control=user_access_control,
    )


def create_feature_request_evidence(
    *,
    team_id: int,
    feature_request_id: UUID,
    input: contracts.CreateFeatureRequestEvidenceInput,
    actor_id: int,
    user_access_control: "UserAccessControl",
) -> contracts.FeatureRequestView | None:
    validated_evidence = _validate_evidence(team_id=team_id, input=input)
    with transaction.atomic():
        result = _get_evidence_account_link(
            team_id=team_id,
            feature_request_id=feature_request_id,
            account_link_id=input.account_link_id,
            expected_version=input.expected_version,
            user_access_control=user_access_control,
        )
        if result is None:
            return None
        feature_request, account_link = result
        evidence = FeatureRequestEvidence.objects.for_team(team_id).create(
            team_id=team_id,
            account_link=account_link,
            summary=validated_evidence.summary,
            customer_quote=validated_evidence.customer_quote,
            source=validated_evidence.source,
            source_url=validated_evidence.source_url,
            requested_on=input.requested_on,
            image_ids=list(validated_evidence.image_ids),
            created_by_id=actor_id,
            updated_by_id=actor_id,
        )
        _record_evidence_change(
            feature_request=feature_request,
            before=None,
            after=_evidence_snapshot(evidence, account=account_link.account),
            actor_id=actor_id,
        )
    return _refresh_feature_request(
        team_id=team_id,
        feature_request_id=feature_request_id,
        user_access_control=user_access_control,
    )


def update_feature_request_evidence(
    *,
    team_id: int,
    feature_request_id: UUID,
    input: contracts.UpdateFeatureRequestEvidenceInput,
    actor_id: int,
    user_access_control: "UserAccessControl",
) -> contracts.FeatureRequestView | None:
    with transaction.atomic():
        evidence = (
            FeatureRequestEvidence.objects.for_team(team_id)
            .select_related("account_link__account")
            .filter(id=input.evidence_id, account_link__feature_request_id=feature_request_id)
            .first()
        )
        if evidence is None:
            return None
        result = _get_evidence_account_link(
            team_id=team_id,
            feature_request_id=feature_request_id,
            account_link_id=evidence.account_link_id,
            expected_version=input.expected_version,
            user_access_control=user_access_control,
        )
        if result is None:
            return None
        feature_request, account_link = result
        validated_evidence = _validate_evidence(
            team_id=team_id,
            input=input,
            current_image_ids=tuple(evidence.image_ids),
        )
        before = _evidence_snapshot(evidence, account=account_link.account)
        evidence.summary = validated_evidence.summary
        evidence.customer_quote = validated_evidence.customer_quote
        evidence.source = validated_evidence.source
        evidence.source_url = validated_evidence.source_url
        evidence.requested_on = input.requested_on
        evidence.image_ids = list(validated_evidence.image_ids)
        after = _evidence_snapshot(evidence, account=account_link.account)
        if before != after:
            evidence.updated_by_id = actor_id
            evidence.save(
                update_fields=[
                    "summary",
                    "customer_quote",
                    "source",
                    "source_url",
                    "requested_on",
                    "image_ids",
                    "updated_by_id",
                    "updated_at",
                ]
            )
            _record_evidence_change(
                feature_request=feature_request,
                before=before,
                after=after,
                actor_id=actor_id,
            )
    return _refresh_feature_request(
        team_id=team_id,
        feature_request_id=feature_request_id,
        user_access_control=user_access_control,
    )


def delete_feature_request_evidence(
    *,
    team_id: int,
    feature_request_id: UUID,
    input: contracts.DeleteFeatureRequestEvidenceInput,
    actor_id: int,
    user_access_control: "UserAccessControl",
) -> contracts.FeatureRequestView | None:
    with transaction.atomic():
        evidence = (
            FeatureRequestEvidence.objects.for_team(team_id)
            .select_related("account_link__account")
            .filter(id=input.evidence_id, account_link__feature_request_id=feature_request_id)
            .first()
        )
        if evidence is None:
            return None
        result = _get_evidence_account_link(
            team_id=team_id,
            feature_request_id=feature_request_id,
            account_link_id=evidence.account_link_id,
            expected_version=input.expected_version,
            user_access_control=user_access_control,
        )
        if result is None:
            return None
        feature_request, account_link = result
        before = _evidence_snapshot(evidence, account=account_link.account)
        evidence.delete()
        _record_evidence_change(
            feature_request=feature_request,
            before=before,
            after=None,
            actor_id=actor_id,
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
            field = change.get("field")
            for value in (change.get("before"), change.get("after")):
                if field == "account":
                    account_ids = [_history_account_id(value)]
                elif field == "accounts" and isinstance(value, list):
                    account_ids = [_history_account_id(item) for item in value]
                elif field == "evidence":
                    account_ids = [_evidence_history_account_id(value)]
                else:
                    account_ids = []
                history_account_ids.update(account_id for account_id in account_ids if account_id is not None)
    accessible_account_ids = set(
        user_access_control.filter_queryset_by_access_level(Account.objects.for_team(team_id))
        .filter(id__in=history_account_ids)
        .values_list("id", flat=True)
    )
    actors = User.objects.filter(id__in={entry.actor_id for entry in history if entry.actor_id is not None})
    actor_names = {actor.id: actor.get_full_name().strip() or actor.email for actor in actors}
    visible_history: list[contracts.FeatureRequestHistoryView] = []
    for entry in history:
        visible_changes = _redact_inaccessible_history_accounts(entry.changes, accessible_account_ids)
        if not visible_changes:
            continue
        visible_history.append(
            contracts.FeatureRequestHistoryView(
                id=entry.id,
                changes=visible_changes,
                is_initial=entry.is_initial,
                change_source=entry.source,
                actor_id=entry.actor_id,
                actor_name=actor_names.get(entry.actor_id),
                changed_at=entry.changed_at,
            )
        )
    return visible_history


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
