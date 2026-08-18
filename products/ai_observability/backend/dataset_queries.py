from uuid import UUID

from django.db.models import F, OuterRef, QuerySet, Subquery

from products.ai_observability.backend.models.datasets import DatasetItemVersion, DatasetRevision


def consistent_dataset_item_versions(
    queryset: QuerySet[DatasetItemVersion, DatasetItemVersion],
) -> QuerySet[DatasetItemVersion, DatasetItemVersion]:
    return queryset.filter(
        team_id=F("dataset_item__team_id"),
        dataset_id=F("dataset_item__dataset_id"),
    ).filter(
        team_id=F("dataset_revision__team_id"),
        dataset_id=F("dataset_revision__dataset_id"),
    )


def latest_dataset_revision(*, team_id: int, dataset_id: UUID) -> DatasetRevision | None:
    return (
        DatasetRevision.objects.for_team(team_id, canonical=True)
        .filter(dataset_id=dataset_id)
        .order_by("-revision")
        .first()
    )


def dataset_item_versions_at_revision(
    *,
    team_id: int,
    dataset_id: UUID,
    revision: int,
    archived: bool,
) -> QuerySet[DatasetItemVersion, DatasetItemVersion]:
    latest_version_id = (
        consistent_dataset_item_versions(DatasetItemVersion.objects.for_team(team_id, canonical=True))
        .filter(
            dataset_item_id=OuterRef("dataset_item_id"),
            dataset_id=dataset_id,
            dataset_revision__revision__lte=revision,
        )
        .order_by("-dataset_revision__revision")
        .values("id")[:1]
    )
    return consistent_dataset_item_versions(DatasetItemVersion.objects.for_team(team_id, canonical=True)).filter(
        dataset_id=dataset_id,
        dataset_revision__revision__lte=revision,
        id=Subquery(latest_version_id),
        archived=archived,
    )
