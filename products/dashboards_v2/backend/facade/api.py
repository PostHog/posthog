"""
Facade for dashboards_v2.

The ONLY module other products are allowed to import.
Accept frozen dataclasses, call logic/, return frozen
dataclasses. Never return ORM instances or import DRF.
"""

from posthog.models import User
from posthog.paging import Page, PageRequest

from ..logic import dashboards
from ..models import DashboardV2
from . import contracts


def _to_user(user: User | None) -> contracts.DashboardV2User | None:
    if user is None:
        return None
    return contracts.DashboardV2User(
        id=user.id,
        uuid=user.uuid,
        distinct_id=user.distinct_id,
        first_name=user.first_name,
        last_name=user.last_name,
        email=user.email,
        is_email_verified=user.is_email_verified,
        hedgehog_config=user.hedgehog_config,
        role_at_organization=user.role_at_organization,
    )


def _to_summary(dashboard: DashboardV2) -> contracts.DashboardV2Summary:
    return contracts.DashboardV2Summary(
        id=dashboard.id,
        uid=dashboard.uid,
        title=dashboard.title,
        # logic.list_dashboards annotates this, so the model type does not declare it.
        description=dashboard.spec_description,  # type: ignore[attr-defined]
        folder=dashboard.folder,
        tags=dashboard.tags,
        version=dashboard.version,
        created_at=dashboard.created_at,
        created_by=_to_user(dashboard.created_by),
        last_modified_at=dashboard.last_modified_at,
        last_modified_by=_to_user(dashboard.last_modified_by),
    )


def _to_detail(dashboard: DashboardV2) -> contracts.DashboardV2Detail:
    return contracts.DashboardV2Detail(
        id=dashboard.id,
        uid=dashboard.uid,
        title=dashboard.title,
        description=dashboard.spec.get("description"),
        folder=dashboard.folder,
        tags=dashboard.tags,
        version=dashboard.version,
        created_at=dashboard.created_at,
        created_by=_to_user(dashboard.created_by),
        last_modified_at=dashboard.last_modified_at,
        last_modified_by=_to_user(dashboard.last_modified_by),
        spec=dashboard.spec,
    )


def list_dashboards(
    team_id: int, page: PageRequest, *, search: str | None = None
) -> Page[contracts.DashboardV2Summary]:
    return dashboards.list_dashboards(team_id, page, search=search).map(_to_summary)


def get_dashboard(team_id: int, uid: str) -> contracts.DashboardV2Detail:
    return _to_detail(dashboards.get_dashboard(team_id, uid))


def create_dashboard(
    team_id: int, user_id: int | None, data: contracts.CreateDashboardV2Input
) -> contracts.DashboardV2Detail:
    return _to_detail(dashboards.create_dashboard(team_id, user_id, data))


def update_dashboard(
    team_id: int, uid: str, user_id: int | None, data: contracts.UpdateDashboardV2Input
) -> contracts.DashboardV2Detail:
    return _to_detail(dashboards.update_dashboard(team_id, uid, user_id, data))


def delete_dashboard(team_id: int, uid: str) -> None:
    dashboards.delete_dashboard(team_id, uid)
