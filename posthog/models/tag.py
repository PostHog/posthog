from collections.abc import Collection, Iterator, Mapping
from contextlib import contextmanager
from typing import Any, ClassVar

from django.db import connections, models, router, transaction

from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.utils import RootTeamManager, RootTeamMixin, RootTeamQuerySet, UUIDTModel


def tagify(tag: str):
    return tag.strip().lower()


@contextmanager
def tag_assignment_transaction(team_ids: Collection[int], *, using: str | None = None) -> Iterator[str]:
    using = using or router.db_for_write(Tag)
    # Inline writers visit tags by name, so serialize within a team before taking ordered tag locks.
    # parent_team_id is bigint in production and id is integer, so cast both keys to the (int, int) overload.
    with transaction.atomic(using=using):
        if team_ids:
            with connections[using].cursor() as cursor:
                cursor.execute(
                    """
                    SELECT pg_advisory_xact_lock(%s::integer, root_team_id::integer)
                    FROM (
                        SELECT DISTINCT COALESCE(parent_team_id, id) AS root_team_id
                        FROM posthog_team WHERE id = ANY(%s)
                        ORDER BY root_team_id
                    ) AS teams
                    """,
                    [5521735, list(team_ids)],
                )
        yield using


class TagQuerySet(RootTeamQuerySet["Tag"]):
    def get_or_create(self, defaults: Mapping[str, Any] | None = None, **kwargs: Any) -> tuple["Tag", bool]:
        team_id = kwargs.get("team_id")
        if team_id is None:
            return super().get_or_create(defaults=defaults, **kwargs)
        with tag_assignment_transaction([team_id], using=getattr(self, "_db", None)) as using:
            return super(TagQuerySet, self.using(using)).get_or_create(defaults=defaults, **kwargs)


class TagManager(RootTeamManager["Tag"]):
    def get_queryset(self) -> TagQuerySet:
        return TagQuerySet(self.model, using=self._db)


class Tag(ModelActivityMixin, UUIDTModel, RootTeamMixin):
    name = models.CharField(max_length=255)
    team = models.ForeignKey("Team", on_delete=models.CASCADE)
    objects: ClassVar[TagManager] = TagManager()

    class Meta:
        unique_together = ("name", "team")

    def __str__(self):
        return self.name
