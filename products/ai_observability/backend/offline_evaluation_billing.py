from datetime import UTC, datetime

from django.db.models import Sum
from django.utils import timezone

from posthog.models import Organization, Team

from products.ai_observability.backend.models.offline_evaluations import OfflineEvaluationUsageLedger


def get_offline_evaluation_usage(period_start: datetime, period_end: datetime) -> dict[str, dict[int, int]]:
    """Billable quantities by acceptance organization and environment, without consuming the ledger."""
    if timezone.is_naive(period_start) or timezone.is_naive(period_end) or period_start >= period_end:
        raise ValueError("Offline evaluation usage requires an aware, increasing reporting window")

    rows = (
        OfflineEvaluationUsageLedger.objects.unscoped()
        .filter(
            accepted_at__gte=period_start.astimezone(UTC),
            accepted_at__lt=period_end.astimezone(UTC),
            team_id__in=Team.objects.filter(is_demo=False, organization__for_internal_metrics=False).values("id"),
            organization_id__in=Organization.objects.filter(for_internal_metrics=False).values("id"),
        )
        .values("organization_id", "team_id")
        .annotate(total_quantity=Sum("quantity"))
    )
    usage: dict[str, dict[int, int]] = {}
    for row in rows:
        usage.setdefault(str(row["organization_id"]), {})[row["team_id"]] = int(row["total_quantity"])
    return usage
