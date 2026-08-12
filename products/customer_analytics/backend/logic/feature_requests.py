from typing import TYPE_CHECKING
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import QuerySet

from products.customer_analytics.backend.facade import contracts
from products.customer_analytics.backend.models import (
    Account,
    FeatureRequest,
    FeatureRequestAccountLink,
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
    *, team_id: int, user_access_control: "UserAccessControl", offset: int, limit: int
) -> tuple[list[contracts.FeatureRequestView], int]:
    queryset = _feature_request_queryset(team_id, user_access_control).order_by("-updated_at", "-created_at", "-id")
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
    if not description:
        raise FeatureRequestValidationError("description", "Enter a description.")
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

    accessible_account = (
        user_access_control.filter_queryset_by_access_level(Account.objects.for_team(team_id))
        .filter(id=input.account_id)
        .first()
    )
    if accessible_account is None:
        raise FeatureRequestValidationError("account_id", "Select an account you can access.")

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

    refreshed = _feature_request_queryset(team_id, user_access_control).filter(id=feature_request.id).first()
    if refreshed is None:
        raise FeatureRequestValidationError("idempotency_key", "This idempotency key is already in use.")
    return contracts.FeatureRequestCreateOutcome(request=_to_feature_request_view(refreshed), created=created)
