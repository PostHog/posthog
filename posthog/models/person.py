from typing import Any, List

from django.apps import apps
from django.db import models, transaction

from posthog.models.utils import UUIDT


class PersonManager(models.Manager):
    def create(self, *args: Any, **kwargs: Any):
        with transaction.atomic():
            if not kwargs.get("distinct_ids"):
                return super().create(*args, **kwargs)
            distinct_ids = kwargs.pop("distinct_ids")
            person = super().create(*args, **kwargs)
            person.add_distinct_ids(distinct_ids)
            return person

    @staticmethod
    def distinct_ids_exist(team_id: int, distinct_ids: List[str]) -> bool:
        return PersonDistinctId.objects.filter(team_id=team_id, distinct_id__in=distinct_ids).exists()


class Person(models.Model):
    @property
    def distinct_ids(self) -> List[str]:
        if hasattr(self, "distinct_ids_cache"):
            return [id.distinct_id for id in self.distinct_ids_cache]  # type: ignore
        return [
            id[0]
            for id in PersonDistinctId.objects.filter(person=self, team_id=self.team_id)
            .order_by("id")
            .values_list("distinct_id")
        ]

    def add_distinct_id(self, distinct_id: str) -> None:
        PersonDistinctId.objects.create(person=self, distinct_id=distinct_id, team_id=self.team_id)

    def add_distinct_ids(self, distinct_ids: List[str]) -> None:
        for distinct_id in distinct_ids:
            self.add_distinct_id(distinct_id)

    def merge_people(self, people_to_merge: List["Person"]):
        CohortPeople = apps.get_model(app_label="posthog", model_name="CohortPeople")

        first_seen = self.created_at

        # merge the properties
        for other_person in people_to_merge:
            self.properties = {**other_person.properties, **self.properties}
            if other_person.created_at < first_seen:
                # Keep the oldest created_at (i.e. the first time we've seen this person)
                first_seen = other_person.created_at
        self.created_at = first_seen
        self.save()

        # merge the distinct_ids
        for other_person in people_to_merge:
            other_person_distinct_ids = PersonDistinctId.objects.filter(person=other_person, team_id=self.team_id)
            for person_distinct_id in other_person_distinct_ids:
                person_distinct_id.person = self
                person_distinct_id.save()

            other_person_cohort_ids = CohortPeople.objects.filter(person=other_person)
            for person_cohort_id in other_person_cohort_ids:
                person_cohort_id.person = self
                person_cohort_id.save()

            other_person.delete()

    objects = PersonManager()
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True, blank=True)
    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    properties: models.JSONField = models.JSONField(default=dict)
    is_user: models.ForeignKey = models.ForeignKey("User", on_delete=models.CASCADE, null=True, blank=True)
    is_identified: models.BooleanField = models.BooleanField(default=False)
    uuid = models.UUIDField(db_index=True, default=UUIDT, editable=False)

    # Has an index on properties -> email from migration 0121, (team_id, id DESC) from migration 0164


class PersonDistinctId(models.Model):
    class Meta:
        constraints = [models.UniqueConstraint(fields=["team", "distinct_id"], name="unique distinct_id for team")]

    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    person: models.ForeignKey = models.ForeignKey(Person, on_delete=models.CASCADE)
    distinct_id: models.CharField = models.CharField(max_length=400)
