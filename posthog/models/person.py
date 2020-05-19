from django.db import models, transaction
from django.contrib.postgres.fields import JSONField
from typing import Any, List


class PersonManager(models.Manager):
    def create(self, *args: Any, **kwargs: Any):
        with transaction.atomic():
            if not kwargs.get("distinct_ids"):
                return super().create(*args, **kwargs)
            distinct_ids = kwargs.pop("distinct_ids")
            person = super().create(*args, **kwargs)
            person.add_distinct_ids(distinct_ids)
            return person


class Person(models.Model):
    @property
    def distinct_ids(self) -> List[str]:
        if hasattr(self, "distinct_ids_cache"):
            return [id.distinct_id for id in self.distinct_ids_cache]  # type: ignore
        return [
            id[0]
            for id in PersonDistinctId.objects.filter(person=self)
            .order_by("id")
            .values_list("distinct_id")
        ]

    def add_distinct_id(self, distinct_id: str) -> None:
        PersonDistinctId.objects.create(
            person=self, distinct_id=distinct_id, team_id=self.team_id
        )

    def add_distinct_ids(self, distinct_ids: List[str]) -> None:
        for distinct_id in distinct_ids:
            self.add_distinct_id(distinct_id)

    objects = PersonManager()
    created_at: models.DateTimeField = models.DateTimeField(
        auto_now_add=True, blank=True
    )
    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    properties: JSONField = JSONField(default=dict)
    is_user: models.ForeignKey = models.ForeignKey(
        "User", on_delete=models.CASCADE, null=True, blank=True
    )


class PersonDistinctId(models.Model):
    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["team", "distinct_id"], name="unique distinct_id for team"
            )
        ]

    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    person: models.ForeignKey = models.ForeignKey(Person, on_delete=models.CASCADE)
    distinct_id: models.CharField = models.CharField(max_length=400)
