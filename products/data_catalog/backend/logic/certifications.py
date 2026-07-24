"""Table/view certification lifecycle.

A certification is a human-vouched trust mark on a warehouse table or view. Targets can be addressed
by id or (for convenience) by name; because ``DataWarehouseTable.name`` is not team-unique (resyncs
leave newest-wins duplicates), an ambiguous name returns a 409 listing the candidates so the caller
picks explicitly. Revocation is a hard delete; both are activity-logged.
"""

from typing import TYPE_CHECKING, Optional
from uuid import UUID

from django.db import IntegrityError, transaction
from django.db.models import QuerySet
from django.utils import timezone

from rest_framework.exceptions import ValidationError

from posthog.models import Team, User
from posthog.models.activity_logging.activity_log import Change, Detail, log_activity

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


def _resolve_table(team: Team, table_id: str | UUID | None, table_name: str | None) -> DataWarehouseTable:
    # queryable() drops soft-deleted tables and those orphaned by a soft-deleted source.
    live = DataWarehouseTable.objects.queryable().filter(team_id=team.id)
    if table_id:
        table = live.filter(id=table_id).first()
        if table is None:
            raise ValidationError({"table_id": "Table not found."})
        return table
    matches = list(live.filter(name=table_name))
    if not matches:
        raise ValidationError({"table_name": f"No table named '{table_name}'."})
    if len(matches) > 1:
        raise CatalogConflict(
            detail=f"Multiple tables named '{table_name}'. Pass table_id to disambiguate.",
            extra={"candidates": [{"id": str(t.id), "created_at": t.created_at.isoformat()} for t in matches]},
        )
    return matches[0]


def _resolve_saved_query(
    team: Team, saved_query_id: str | UUID | None, view_name: str | None
) -> DataWarehouseSavedQuery:
    live = DataWarehouseSavedQuery.objects.filter(team_id=team.id, deleted=False)
    if saved_query_id:
        saved_query = live.filter(id=saved_query_id).first()
        if saved_query is None:
            raise ValidationError({"saved_query_id": "View not found."})
        return saved_query
    matches = list(live.filter(name=view_name))
    if not matches:
        raise ValidationError({"view_name": f"No view named '{view_name}'."})
    if len(matches) > 1:
        raise CatalogConflict(
            detail=f"Multiple views named '{view_name}'. Pass saved_query_id to disambiguate.",
            extra={"candidates": [{"id": str(v.id), "created_at": v.created_at.isoformat()} for v in matches]},
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
    request: "Request | None" = None,
) -> TableCertification:
    selectors = {
        "table_id": table_id,
        "saved_query_id": saved_query_id,
        "table_name": table_name,
        "view_name": view_name,
    }
    if sum(value is not None for value in selectors.values()) != 1:
        raise ValidationError({"target": "Provide exactly one of table_id, saved_query_id, table_name, or view_name."})

    target_table = target_saved_query = None
    if table_id is not None or table_name is not None:
        target_table = _resolve_table(team, table_id, table_name)
    else:
        target_saved_query = _resolve_saved_query(team, saved_query_id, view_name)

    certifications = TableCertification.objects.for_team(team.id, canonical=True)
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
        TableCertification.objects.for_team(team.id, canonical=True)
        .exclude(table__deleted=True)
        .exclude(table__external_data_source__deleted=True)
        .exclude(saved_query__deleted=True)
        .select_related("table", "saved_query", "certified_by")
        .order_by("-created_at")
    )
