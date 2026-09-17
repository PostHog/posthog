from uuid import UUID

from django.db.models import CharField, Q, QuerySet
from django.db.models.functions import Cast

from posthog.models.activity_logging.activity_log import ActivityLog

from ..models import DataQualityCheck


def model_activity(queryset: QuerySet[ActivityLog], team_id: int, saved_query_id: str) -> QuerySet[ActivityLog]:
    try:
        view_id = UUID(saved_query_id)
    except ValueError:
        return queryset.none()
    checks = (
        DataQualityCheck.objects.for_team(team_id)
        .filter(saved_query_id=view_id)
        .annotate(activity_item_id=Cast("id", output_field=CharField()))
        .values("activity_item_id")
    )
    return queryset.filter(team_id=team_id).filter(
        Q(item_id=saved_query_id) | Q(scope="DataQualityCheck", item_id__in=checks)
    )
