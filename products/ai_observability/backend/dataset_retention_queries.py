from datetime import datetime

from django.db.models import (
    Case,
    DateTimeField,
    ExpressionWrapper,
    F,
    IntegerField,
    OuterRef,
    Q,
    QuerySet,
    Subquery,
    Value,
    When,
)
from django.db.models.functions import Coalesce, Least

from products.ai_observability.backend.dataset_retention import (
    ACTIVE_RETENTION,
    HISTORY_RETENTION,
    USAGE_REFRESH_INTERVAL,
)
from products.ai_observability.backend.models.datasets import Dataset, DatasetRevision


class DatasetRetentionQuery:
    @staticmethod
    def dataset_expiry(prefix: str = "") -> ExpressionWrapper:
        return ExpressionWrapper(
            F(f"{prefix}last_used_at")
            + Case(
                When(**{f"{prefix}archived": True}, then=Value(HISTORY_RETENTION)),
                default=Value(ACTIVE_RETENTION),
            )
            + Value(USAGE_REFRESH_INTERVAL),
            output_field=DateTimeField(),
        )

    @classmethod
    def datasets(cls, visible_datasets: QuerySet[Dataset], before: datetime) -> QuerySet[Dataset]:
        return (
            visible_datasets.select_related(None)
            .prefetch_related(None)
            .filter(
                Q(archived=True, last_used_at__lte=before - HISTORY_RETENTION - USAGE_REFRESH_INTERVAL)
                | Q(archived=False, last_used_at__lte=before - ACTIVE_RETENTION - USAGE_REFRESH_INTERVAL)
            )
            .annotate(
                dataset_id=F("id"),
                dataset_name=F("name"),
                dataset_archived=F("archived"),
                revision=Value(None, output_field=IntegerField()),
                expires_at=cls.dataset_expiry(),
            )
            .only("id", "name", "archived", "last_used_at")
            .order_by("expires_at", "id")
        )

    @classmethod
    def revisions(
        cls, visible_datasets: QuerySet[Dataset], team_id: int, before: datetime
    ) -> QuerySet[DatasetRevision]:
        latest_revision = (
            DatasetRevision.objects.for_team(team_id, canonical=True)
            .filter(dataset_id=OuterRef("dataset_id"))
            .order_by("-revision")
        )
        revisions = (
            DatasetRevision.objects.for_team(team_id, canonical=True)
            .filter(dataset_id__in=visible_datasets.values("id"), expired_at__isnull=True, last_used_at__isnull=False)
            .alias(
                current_revision_id=Coalesce(
                    F("dataset__current_revision_id"), Subquery(latest_revision.values("id")[:1])
                )
            )
            .exclude(id=F("current_revision_id"))
            .annotate(
                dataset_name=F("dataset__name"),
                dataset_archived=F("dataset__archived"),
                expires_at=Least(
                    ExpressionWrapper(
                        F("last_used_at") + Value(HISTORY_RETENTION + USAGE_REFRESH_INTERVAL),
                        output_field=DateTimeField(),
                    ),
                    cls.dataset_expiry("dataset__"),
                ),
            )
            .only("id", "dataset_id", "revision")
            .order_by()
        )
        history_cutoff = before - HISTORY_RETENTION - USAGE_REFRESH_INTERVAL
        expiring_datasets = cls.datasets(visible_datasets, before).order_by().values("id")
        return (
            revisions.filter(last_used_at__lte=history_cutoff)
            .union(
                revisions.filter(last_used_at__gt=history_cutoff, dataset_id__in=expiring_datasets),
                all=True,
            )
            .order_by("expires_at", "id")
        )
