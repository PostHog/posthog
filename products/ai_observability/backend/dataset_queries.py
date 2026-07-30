from uuid import UUID

from django.db.models import OuterRef, QuerySet, Subquery

from products.ai_observability.backend.models.datasets import DatasetItemVersion


def dataset_item_versions_at_revision(
    *,
    team_id: int,
    dataset_id: UUID,
    revision: int,
    archived: bool,
) -> QuerySet[DatasetItemVersion, DatasetItemVersion]:
    latest_version_id = (
        DatasetItemVersion.objects.for_team(team_id, canonical=True)
        .filter(
            dataset_item_id=OuterRef("dataset_item_id"),
            dataset_revision__dataset_id=dataset_id,
            dataset_revision__revision__lte=revision,
        )
        .order_by("-dataset_revision__revision")
        .values("id")[:1]
    )
    return DatasetItemVersion.objects.for_team(team_id, canonical=True).filter(
        dataset_item__dataset_id=dataset_id,
        dataset_revision__revision__lte=revision,
        id=Subquery(latest_version_id),
        archived=archived,
    )
