"""Clearing the legacy row link on investigations of insight alerts the platform owns, so deleting the
rows does not delete the investigations with them. Every reader finds an investigation by its platform
alert, so nothing reads the link."""

from products.alerts.backend.models.investigation import InsightAlertInvestigation
from products.alerts_platform.backend.facade.api import owned_copies_by_legacy_id
from products.alerts_platform.backend.facade.contracts import SourceKind


def teams_with_row_linked_investigations() -> list[int]:
    # nosemgrep: idor-lookup-without-team (an operator command listing the teams it will visit; no request input)
    rows = InsightAlertInvestigation.objects.unscoped().filter(alert_configuration__isnull=False)
    return sorted(set(rows.values_list("team_id", flat=True)))


def detach_investigations_from_rows(team_id: int, *, batch_size: int, apply: bool) -> int:
    rows = InsightAlertInvestigation.objects.for_team(team_id).filter(alert_configuration__isnull=False)
    row_ids = set(rows.values_list("alert_configuration_id", flat=True).distinct())
    if not row_ids:
        return 0
    owned = owned_copies_by_legacy_id(team_id=team_id, source_kind=SourceKind.INSIGHT, legacy_configuration_ids=row_ids)
    linked = rows.filter(alert_configuration_id__in=list(owned))
    if not apply:
        return linked.count()
    detached = 0
    while ids := list(linked.values_list("id", flat=True)[:batch_size]):
        # A queryset update, which writes no activity log entry and leaves `updated_at` as it was.
        detached += (
            InsightAlertInvestigation.objects.for_team(team_id).filter(id__in=ids).update(alert_configuration=None)
        )
    return detached
