"""Table/view certification lifecycle.

A certification is a human-vouched trust mark on a warehouse table or view. Targets can be addressed
by id or (for convenience) by name; because ``DataWarehouseTable.name`` is not team-unique (resyncs
leave newest-wins duplicates), an ambiguous name returns a 409 listing the candidates so the caller
picks explicitly. Revocation is a hard delete; both are activity-logged.
"""

from typing import TYPE_CHECKING, Optional, TypeVar
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import Model, QuerySet
from django.utils import timezone

from rest_framework.exceptions import ValidationError

from posthog.hogql.database.database import get_data_warehouse_table_name

from posthog.models import Team, User
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity
from posthog.scopes import APIScopeObject

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.warehouse_sources.backend.facade.models import DataWarehouseTable

from ..facade.enums import CertificationStatus
from ..models import TableCertification
from .analytics import (
    CERTIFICATION_CERTIFIED_EVENT,
    CERTIFICATION_DEPRECATED_EVENT,
    CERTIFICATION_PROPOSED_EVENT,
    CERTIFICATION_REVOKED_EVENT,
    capture_certification_event,
    certification_target_name,
)
from .exceptions import CatalogConflict

if TYPE_CHECKING:
    from rest_framework.request import Request

_SCOPE = "TableCertification"

_Target = TypeVar("_Target", bound=Model)


def _log(user: Optional[User], cert: TableCertification, activity: str, changes: Optional[list[Change]] = None) -> None:
    log_activity(
        organization_id=None,
        team_id=cert.team_id,
        user=user,
        was_impersonated=False,
        item_id=str(cert.id),
        scope=_SCOPE,
        activity=activity,
        detail=Detail(name=certification_target_name(cert), changes=changes),
    )


def _duplicate_target_conflict(certification: TableCertification) -> CatalogConflict:
    return CatalogConflict(detail=f"This target is already marked '{certification.status}'.")


def _visible_targets(
    uac: Optional[UserAccessControl], team: Team, targets: list[_Target], resource: APIScopeObject
) -> list[_Target]:
    if uac is None:
        return targets
    if targets:
        uac.preload_access_levels(team=team, resource=resource)
    return [target for target in targets if uac.check_access_level_for_object(target, "viewer")]


def _resolve_table(
    team: Team, uac: Optional[UserAccessControl], table_id: str | UUID | None, table_name: str | None
) -> DataWarehouseTable:
    # raw_objects skips the default manager's externaldataschema_set prefetch and created_by join,
    # which this path never reads; queryable() still drops soft-deleted and orphaned tables.
    live = DataWarehouseTable.raw_objects.queryable().filter(team_id=team.id).select_related("external_data_source")
    if table_id:
        table = live.filter(id=table_id).first()
        if table is None or not _visible_targets(uac, team, [table], "warehouse_table"):
            raise ValidationError({"table_id": "Table not found."})
        return table
    matches = list(live.filter(name=table_name).defer("columns"))
    if table_name is not None and "." in table_name:
        suffix = table_name.rsplit(".", 1)[-1]
        matches += [
            table
            for table in live.exclude(name=table_name).filter(name__iendswith=suffix).defer("columns")
            if get_data_warehouse_table_name(table.external_data_source, table.name) == table_name
        ]
    matches = _visible_targets(uac, team, matches, "warehouse_table")
    if not matches:
        raise ValidationError({"table_name": f"No table named '{table_name}'."})
    if len(matches) > 1:
        raise CatalogConflict(
            detail=f"Multiple tables named '{table_name}'. Pass table_id to disambiguate.",
            extra={
                "candidates": [
                    {
                        "id": str(table.id),
                        "created_at": table.created_at.isoformat(),
                        "name": table.name,
                        "source_id": str(table.external_data_source_id) if table.external_data_source_id else None,
                        "source_prefix": table.external_data_source.prefix if table.external_data_source else None,
                    }
                    for table in matches
                ]
            },
        )
    return matches[0]


def _resolve_saved_query(
    team: Team, uac: Optional[UserAccessControl], saved_query_id: str | UUID | None, view_name: str | None
) -> DataWarehouseSavedQuery:
    live = DataWarehouseSavedQuery.objects.filter(team_id=team.id, deleted=False)
    if saved_query_id:
        saved_query = live.filter(id=saved_query_id).first()
        if saved_query is None or not _visible_targets(uac, team, [saved_query], "warehouse_view"):
            raise ValidationError({"saved_query_id": "View not found."})
        return saved_query
    matches = _visible_targets(uac, team, list(live.filter(name=view_name)), "warehouse_view")
    if not matches:
        raise ValidationError({"view_name": f"No view named '{view_name}'."})
    if len(matches) > 1:
        raise CatalogConflict(
            detail=f"Multiple views named '{view_name}'. Pass saved_query_id to disambiguate.",
            extra={
                "candidates": [
                    {"id": str(view.id), "created_at": view.created_at.isoformat(), "name": view.name}
                    for view in matches
                ]
            },
        )
    return matches[0]


def propose_certification(
    *,
    team: Team,
    user: Optional[User],
    table_id: str | UUID | None = None,
    saved_query_id: str | UUID | None = None,
    table_name: str | None = None,
    view_name: str | None = None,
    notes: str = "",
    proposed_status: str = CertificationStatus.CERTIFIED,
    request: "Request | None" = None,
) -> TableCertification:
    if proposed_status not in (CertificationStatus.CERTIFIED, CertificationStatus.DEPRECATED):
        raise ValidationError({"proposed_status": "Must be 'certified' or 'deprecated'."})
    selectors = {
        "table_id": table_id,
        "saved_query_id": saved_query_id,
        "table_name": table_name,
        "view_name": view_name,
    }
    if sum(value is not None for value in selectors.values()) != 1:
        raise ValidationError({"target": "Provide exactly one of table_id, saved_query_id, table_name, or view_name."})

    uac = None if user is None else UserAccessControl(user=user, team=team)
    target_table = target_saved_query = None
    if table_id is not None or table_name is not None:
        target_table = _resolve_table(team, uac, table_id, table_name)
    else:
        target_saved_query = _resolve_saved_query(team, uac, saved_query_id, view_name)

    certifications = TableCertification.objects.for_team(team.id)
    existing = certifications.filter(table=target_table, saved_query=target_saved_query).first()
    if existing is not None:
        raise _duplicate_target_conflict(existing)

    try:
        with transaction.atomic():
            cert = certifications.create(
                team=team,
                table=target_table,
                saved_query=target_saved_query,
                notes=notes,
                proposed_status=proposed_status,
                created_by=user,
            )
    except IntegrityError:
        existing = certifications.filter(table=target_table, saved_query=target_saved_query).first()
        if existing is None:
            raise
        raise _duplicate_target_conflict(existing)

    _log(user, cert, "created")
    capture_certification_event(CERTIFICATION_PROPOSED_EVENT, cert, team=team, user=user, request=request)
    return cert


def certify(cert: TableCertification, user: Optional[User], request: "Request | None" = None) -> TableCertification:
    return _set_status(cert, user, CertificationStatus.CERTIFIED, CERTIFICATION_CERTIFIED_EVENT, request)


def deprecate(cert: TableCertification, user: Optional[User], request: "Request | None" = None) -> TableCertification:
    return _set_status(cert, user, CertificationStatus.DEPRECATED, CERTIFICATION_DEPRECATED_EVENT, request)


def _set_status(
    cert: TableCertification,
    user: Optional[User],
    status: CertificationStatus,
    event: str,
    request: "Request | None" = None,
) -> TableCertification:
    if cert.status == status:
        return cert
    previous = cert.status
    cert.status = status
    cert.certified_by = user
    cert.certified_at = timezone.now()
    cert.save()
    _log(user, cert, "updated", [Change(type=_SCOPE, field="status", before=previous, after=status, action="changed")])
    capture_certification_event(event, cert, team=cert.team, user=user, request=request)
    return cert


def revoke_certification(cert: TableCertification, user: Optional[User], request: "Request | None" = None) -> None:
    _log(user, cert, "deleted")
    capture_certification_event(CERTIFICATION_REVOKED_EVENT, cert, team=cert.team, user=user, request=request)
    cert.delete()


def certifications_for_team(team: Team) -> QuerySet[TableCertification]:
    """Certifications whose target is not soft-deleted, newest first."""
    return (
        TableCertification.objects.for_team(team.id)
        .exclude(table__deleted=True)
        .exclude(table__external_data_source__deleted=True)
        .exclude(saved_query__deleted=True)
        .select_related("table", "table__external_data_source", "saved_query", "certified_by")
        .order_by("-created_at")
    )
