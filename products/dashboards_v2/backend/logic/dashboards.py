from django.db import IntegrityError, transaction
from django.db.models import QuerySet
from django.db.models.fields.json import KT

from posthog.models.utils import strict_fetch
from posthog.paging import Page, PageRequest
from posthog.queryset_paging import select_page

from ..facade.contracts import (
    CreateDashboardV2Input,
    DashboardV2NotFoundError,
    DashboardV2UidTakenError,
    DashboardV2VersionConflictError,
    UpdateDashboardV2Input,
)
from ..facade.spec import SpecValidationError, ValidationIssue, parse_publish, to_document
from ..models import DashboardV2, DashboardV2Version


def _live(team_id: int) -> QuerySet[DashboardV2]:
    return DashboardV2.objects.for_team(team_id).filter(deleted=False)


def list_dashboards(team_id: int, page: PageRequest, *, search: str | None = None) -> Page[DashboardV2]:
    """One page of the team's dashboards, newest change first. Rows carry `spec_description`, not `spec`."""
    dashboards = (
        _live(team_id)
        .select_related("created_by", "last_modified_by")
        .defer("spec")
        .annotate(spec_description=KT("spec__description"))
        .order_by("-last_modified_at")
    )
    if search:
        dashboards = dashboards.filter(title__icontains=search)
    return select_page(strict_fetch(dashboards), page)


def get_dashboard(team_id: int, uid: str) -> DashboardV2:
    try:
        return _live(team_id).select_related("created_by", "last_modified_by").get(uid=uid)
    except DashboardV2.DoesNotExist as error:
        raise DashboardV2NotFoundError(uid) from error


def create_dashboard(team_id: int, user_id: int | None, data: CreateDashboardV2Input) -> DashboardV2:
    spec = parse_publish(data.spec)
    document = to_document(spec)
    try:
        with transaction.atomic():
            dashboard = DashboardV2.objects.for_team(team_id).create(
                team_id=team_id,
                uid=spec.uid,
                spec=document,
                version=1,
                title=spec.title,
                folder=spec.folder or "",
                tags=spec.tags or [],
                created_by_id=user_id,
                last_modified_by_id=user_id,
            )
            DashboardV2Version.objects.for_team(team_id).create(
                team_id=dashboard.team_id, dashboard=dashboard, version=1, spec=document, created_by_id=user_id
            )
    except IntegrityError as error:
        if not _live(team_id).filter(uid=spec.uid).exists():
            raise
        raise DashboardV2UidTakenError(spec.uid) from error
    return dashboard


def update_dashboard(team_id: int, uid: str, user_id: int | None, data: UpdateDashboardV2Input) -> DashboardV2:
    spec = parse_publish(data.spec)
    if spec.uid != uid:
        raise SpecValidationError(
            [
                ValidationIssue(
                    path="uid",
                    message=f'A dashboard cannot be renamed, so the uid must stay "{uid}". Got "{spec.uid}".',
                )
            ]
        )
    document = to_document(spec)
    with transaction.atomic():
        try:
            # The row lock makes concurrent saves wait, so each one checks the version that the one before it wrote.
            dashboard = _live(team_id).select_for_update().get(uid=uid)
        except DashboardV2.DoesNotExist as error:
            raise DashboardV2NotFoundError(uid) from error
        if data.base_version is not None and data.base_version != dashboard.version:
            raise DashboardV2VersionConflictError(base_version=data.base_version, current_version=dashboard.version)
        dashboard.version += 1
        dashboard.spec = document
        dashboard.title = spec.title
        dashboard.folder = spec.folder or ""
        dashboard.tags = spec.tags or []
        dashboard.last_modified_by_id = user_id
        dashboard.save(
            update_fields=["version", "spec", "title", "folder", "tags", "last_modified_by", "last_modified_at"]
        )
        DashboardV2Version.objects.for_team(team_id).create(
            team_id=dashboard.team_id,
            dashboard=dashboard,
            version=dashboard.version,
            spec=document,
            message=data.message,
            created_by_id=user_id,
        )
    return dashboard


def delete_dashboard(team_id: int, uid: str) -> None:
    if not _live(team_id).filter(uid=uid).update(deleted=True):
        raise DashboardV2NotFoundError(uid)
