from typing import Any, List, Optional

from django.db import models, transaction
from django.db.models import F, Q
from django.db.models.expressions import Func
from django.db.models.fields import BooleanField

from posthog.models.utils import UUIDT


class PersonManager(models.Manager):
    def create(self, *args: Any, **kwargs: Any):
        with transaction.atomic():
            if not kwargs.get("distinct_ids"):
                return super().create(*args, **kwargs)
            distinct_ids = kwargs.pop("distinct_ids")
            person = super().create(*args, **kwargs)
            person._add_distinct_ids(distinct_ids)
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

    # :DEPRECATED: This should happen through the plugin server
    def add_distinct_id(self, distinct_id: str) -> None:
        PersonDistinctId.objects.create(person=self, distinct_id=distinct_id, team_id=self.team_id)

    # :DEPRECATED: This should happen through the plugin server
    def _add_distinct_ids(self, distinct_ids: List[str]) -> None:
        for distinct_id in distinct_ids:
            self.add_distinct_id(distinct_id)

    def split_person(self, main_distinct_id: Optional[str]):
        distinct_ids = Person.objects.get(pk=self.pk).distinct_ids
        if not main_distinct_id:
            self.properties = {}
            self.save()
            main_distinct_id = distinct_ids[0]

        for distinct_id in distinct_ids:
            if not distinct_id == main_distinct_id:
                with transaction.atomic():
                    pdi = PersonDistinctId.objects.select_for_update().get(person=self, distinct_id=distinct_id)
                    person = Person.objects.create(team_id=self.team_id)
                    pdi.person_id = str(person.id)
                    pdi.version = (pdi.version or 0) + 1
                    pdi.save(update_fields=["version", "person_id"])

                from posthog.models.person.util import create_person, create_person_distinct_id

                create_person_distinct_id(
                    team_id=self.team_id,
                    distinct_id=distinct_id,
                    person_id=str(person.uuid),
                    is_deleted=False,
                    version=pdi.version,
                )
                create_person(team_id=self.team_id, uuid=str(person.uuid), version=person.version or 0)

    objects = PersonManager()
    created_at: models.DateTimeField = models.DateTimeField(auto_now_add=True, blank=True)

    # used to prevent race conditions with set and set_once
    properties_last_updated_at: models.JSONField = models.JSONField(default=dict, null=True, blank=True)

    # used for evaluating if we need to override the value or not (value: set or set_once)
    properties_last_operation: models.JSONField = models.JSONField(null=True, blank=True)

    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    properties: models.JSONField = models.JSONField(default=dict)
    is_user: models.ForeignKey = models.ForeignKey("User", on_delete=models.CASCADE, null=True, blank=True)
    is_identified: models.BooleanField = models.BooleanField(default=False)
    uuid = models.UUIDField(db_index=True, default=UUIDT, editable=False)

    # current version of the person, used to sync with ClickHouse and collapse rows correctly
    version: models.BigIntegerField = models.BigIntegerField(null=True, blank=True)

    # Has an index on properties -> email from migration 0121, (team_id, id DESC) from migration 0164


class PersonDistinctId(models.Model):
    class Meta:
        constraints = [models.UniqueConstraint(fields=["team", "distinct_id"], name="unique distinct_id for team")]

    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE, db_index=False)
    person: models.ForeignKey = models.ForeignKey(Person, on_delete=models.CASCADE)
    distinct_id: models.CharField = models.CharField(max_length=400)

    # current version of the id, used to sync with ClickHouse and collapse rows correctly for new clickhouse table
    version: models.BigIntegerField = models.BigIntegerField(null=True, blank=True)


class PersonOverride(models.Model):
    """A model of persons to be overriden in merge or merge-like events.

    This model has a set of constraints to ensure correctness:
    1. Unique constraint on (team_id, old_person_id) pairs.
    2. Check that old_person_id is different to override_person_id for every row.
    3. Exclude rows that overlap across old_person_id and override_person_id (e.g. if
        a row exists with old_person_id=123 then we would not allow a row with
        override_person_id=123 to exist, as that would require a self join to figure
        out the ultimate override_person_id required for old_person_id=123).
    """

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "old_person_id"], name="unique override per old_person_id"),
            models.CheckConstraint(
                check=~Q(old_person_id__exact=F("override_person_id")),
                name="old_person_id_different_from_override_person_id",
            ),
            models.CheckConstraint(
                check=Q(
                    Func(
                        F("team_id"),
                        F("override_person_id"),
                        F("old_person_id"),
                        function="is_override_person_not_used_as_old_person",
                        output_field=BooleanField(),
                    )
                ),
                name="old_person_id_is_not_override_person_id",
            ),
        ]

    id = models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")
    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)

    # We don't want to delete rows before we had a chance to propagate updates to the events table.
    # To reduce potential side-effects, these are not ForeingKeys.
    old_person_id = models.UUIDField(db_index=True)
    override_person_id = models.UUIDField(db_index=True)

    oldest_event: models.DateTimeField = models.DateTimeField()
    version: models.BigIntegerField = models.BigIntegerField(null=True, blank=True)


# This function checks two things:
# 1. A new override_person_id must not match an existing old_person_id
# 2. A new old_person_id must not match an existing override_person_id
CREATE_FUNCTION_FOR_CONSTRAINT_SQL = f"""
CREATE OR REPLACE FUNCTION is_override_person_not_used_as_old_person(team_id bigint, override_person_id uuid, old_person_id uuid)
RETURNS BOOLEAN AS $$
  SELECT NOT EXISTS (
    SELECT 1
      FROM "{PersonOverride._meta.db_table}"
      WHERE team_id = $1
      AND override_person_id = $3
    ) AND NOT EXISTS (
        SELECT 1
      FROM "{PersonOverride._meta.db_table}"
      WHERE team_id = $1
      AND old_person_id = $2
    );
$$ LANGUAGE SQL;
"""

DROP_FUNCTION_FOR_CONSTRAINT_SQL = "DROP FUNCTION is_override_person_not_used_as_old_person"
