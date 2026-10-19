from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from django.db import models, transaction
from django.db.models import Exists, Prefetch, QuerySet

from posthog.api.tagged_item import cleanup_orphan_tags, set_tags_on_object
from posthog.models.tagged_item import TaggedItem

if TYPE_CHECKING:
    from products.ai_observability.backend.models.datasets import Dataset
    from products.ai_observability.backend.models.offline_evaluations import OfflineExperiment
    from products.ai_observability.backend.models.score_definitions import ScoreDefinition

    TaggedResource = Dataset | OfflineExperiment | ScoreDefinition


class TagMatch(models.TextChoices):
    ANY = "any", "Any"
    ALL = "all", "All"


class ResourceTags:
    @staticmethod
    def prefetch() -> Prefetch:
        return Prefetch("tagged_items", queryset=TaggedItem.objects.select_related("tag"), to_attr="prefetched_tags")

    @staticmethod
    def names(resource: TaggedResource) -> list[str]:
        items = getattr(resource, "prefetched_tags", None)
        if items is None:
            items = resource.tagged_items.select_related("tag")
        return sorted(item.tag.name for item in items)

    @staticmethod
    def filter[T: models.Model](queryset: QuerySet[T], team_id: int, tags: Sequence[str], match: str) -> QuerySet[T]:
        if not tags:
            return queryset
        assignments = TaggedItem.objects.matching_outer(queryset.model).filter(team_id=team_id, tag__team_id=team_id)
        if match == TagMatch.ALL:
            for tag in sorted(set(tags)):
                queryset = queryset.filter(Exists(assignments.filter(tag__name=tag)))
            return queryset
        return queryset.filter(Exists(assignments.filter(tag__name__in=tags)))

    @staticmethod
    def set(resource: TaggedResource, tags: list[str]) -> None:
        with transaction.atomic():
            # Serialize replacement on the resource so concurrent saves cannot merge two replacement sets.
            type(resource)._base_manager.select_for_update().get(pk=resource.pk, team_id=resource.team_id)
            resource.__dict__["prefetched_tags"] = set_tags_on_object(tags, resource)
            cleanup_orphan_tags(resource.team_id)
