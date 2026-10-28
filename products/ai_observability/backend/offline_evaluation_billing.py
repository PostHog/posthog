from datetime import UTC, datetime

from django.db.models import Sum
from django.utils import timezone

import structlog

from posthog.models import Organization

from products.ai_observability.backend.models.offline_evaluations import OfflineEvaluationUsageLedger

logger = structlog.get_logger(__name__)


def get_offline_evaluation_usage(period_start: datetime, period_end: datetime) -> dict[str, dict[int, int]]:
    """Billable quantities by acceptance organization and environment, without consuming the ledger."""
    if timezone.is_naive(period_start) or timezone.is_naive(period_end) or period_start >= period_end:
        raise ValueError("Offline evaluation usage requires an aware, increasing reporting window")

    rows = list(
        OfflineEvaluationUsageLedger.objects.unscoped()
        .filter(accepted_at__gte=period_start.astimezone(UTC), accepted_at__lt=period_end.astimezone(UTC))
        .values("organization_id", "team_id", "billing_eligible")
        .annotate(total_quantity=Sum("quantity"))
    )
    organizations = dict(
        Organization.objects.filter(id__in={row["organization_id"] for row in rows}).values_list(
            "id", "for_internal_metrics"
        )
    )
    usage: dict[str, dict[int, int]] = {}
    deleted_organizations: set[str] = set()
    for row in rows:
        organization_id = row["organization_id"]
        if organization_id not in organizations:
            deleted_organizations.add(str(organization_id))
            continue
        if organizations[organization_id] or row["billing_eligible"] is False:
            continue
        if row["billing_eligible"] is None:
            raise ValueError("Offline evaluation billing window contains usage without an eligibility snapshot")
        usage.setdefault(str(organization_id), {})[row["team_id"]] = int(row["total_quantity"])
    if deleted_organizations:
        logger.warning(
            "offline_evaluation_usage_for_deleted_organizations",
            organization_count=len(deleted_organizations),
            period_start=period_start.isoformat(),
            period_end=period_end.isoformat(),
        )
    return usage
