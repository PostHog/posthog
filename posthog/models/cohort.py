from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from dateutil.relativedelta import relativedelta
from django.conf import settings
from django.core.exceptions import EmptyResultSet
from django.db import connection, models, transaction
from django.db.models import Q
from django.db.models.expressions import F
from django.utils import timezone
from sentry_sdk import capture_exception

from posthog.models.utils import sane_repr
from posthog.utils import is_clickhouse_enabled

from .action import Action
from .event import Event
from .filters import Filter
from .person import Person

DELETE_QUERY = """
DELETE FROM "posthog_cohortpeople" WHERE "cohort_id" = {cohort_id}
"""

UPDATE_QUERY = """
INSERT INTO "posthog_cohortpeople" ("person_id", "cohort_id")
{values_query}
ON CONFLICT DO NOTHING
"""


class Group(object):
    def __init__(
        self,
        properties: Optional[Dict[str, Any]] = None,
        action_id: Optional[int] = None,
        event_id: Optional[str] = None,
        days: Optional[int] = None,
        count: Optional[int] = None,
        count_operator: Optional[Literal["eq", "lte", "gte"]] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        label: Optional[str] = None,
    ):
        if not properties and not action_id and not event_id:
            raise ValueError("Cohort group needs properties or action_id or event_id")
        self.properties = properties
        self.action_id = action_id
        self.event_id = event_id
        self.label = label
        self.days = days
        self.count = count
        self.count_operator = count_operator
        self.start_date = start_date
        self.end_date = end_date

    def to_dict(self) -> Dict[str, Any]:
        dup = self.__dict__.copy()
        dup["start_date"] = self.start_date.isoformat() if self.start_date else self.start_date
        dup["end_date"] = self.end_date.isoformat() if self.end_date else self.end_date
        return dup


class CohortManager(models.Manager):
    def create(self, *args: Any, **kwargs: Any):
        if kwargs.get("groups"):
            kwargs["groups"] = [Group(**group).to_dict() for group in kwargs["groups"]]
        cohort = super().create(*args, **kwargs)
        return cohort


class Cohort(models.Model):
    name: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    description: models.CharField = models.CharField(max_length=1000, blank=True)
    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    deleted: models.BooleanField = models.BooleanField(default=False)
    groups: models.JSONField = models.JSONField(default=list)
    people: models.ManyToManyField = models.ManyToManyField("Person", through="CohortPeople")

    created_by: models.ForeignKey = models.ForeignKey("User", on_delete=models.SET_NULL, blank=True, null=True)
    created_at: models.DateTimeField = models.DateTimeField(default=timezone.now, blank=True, null=True)
    is_calculating: models.BooleanField = models.BooleanField(default=False)
    last_calculation: models.DateTimeField = models.DateTimeField(blank=True, null=True)
    errors_calculating: models.IntegerField = models.IntegerField(default=0)

    is_static: models.BooleanField = models.BooleanField(default=False)

    objects = CohortManager()

    def get_analytics_metadata(self):
        action_groups_count: int = 0
        properties_groups_count: int = 0
        for group in self.groups:
            action_groups_count += 1 if group.get("action_id") else 0
            properties_groups_count += 1 if group.get("properties") else 0

        return {
            "name_length": len(self.name) if self.name else 0,
            "person_count_precalc": self.people.count(),
            "groups_count": len(self.groups),
            "action_groups_count": action_groups_count,
            "properties_groups_count": properties_groups_count,
            "deleted": self.deleted,
        }

    def calculate_people(self, use_clickhouse=is_clickhouse_enabled()):
        if self.is_static:
            return
        try:
            if not use_clickhouse:
                self.is_calculating = True
                self.save()
                persons_query = self._postgres_persons_query()
            else:
                persons_query = self._clickhouse_persons_query()

            try:
                sql, params = persons_query.distinct("pk").only("pk").query.sql_with_params()
            except EmptyResultSet:
                query = DELETE_QUERY.format(cohort_id=self.pk)
                params = {}
            else:
                query = f"""
                    {DELETE_QUERY};
                    {UPDATE_QUERY};
                """.format(
                    cohort_id=self.pk,
                    values_query=sql.replace('FROM "posthog_person"', f', {self.pk} FROM "posthog_person"', 1,),
                )

            cursor = connection.cursor()
            with transaction.atomic():
                cursor.execute(query, params)
                if not use_clickhouse:
                    self.last_calculation = timezone.now()
                    self.errors_calculating = 0
        except Exception as err:
            if not use_clickhouse:
                self.errors_calculating = F("errors_calculating") + 1
            raise err
        finally:
            if not use_clickhouse:
                self.is_calculating = False
                self.save()

    def calculate_people_ch(self):
        if is_clickhouse_enabled():
            from ee.clickhouse.models.cohort import recalculate_cohortpeople
            from posthog.tasks.calculate_cohort import calculate_cohort

            try:
                recalculate_cohortpeople(self)
                calculate_cohort(self.id)
                self.last_calculation = timezone.now()
                self.errors_calculating = 0
            except Exception as e:
                self.errors_calculating = F("errors_calculating") + 1
                raise e
            finally:
                self.is_calculating = False
                self.save()

    def insert_users_by_list(self, items: List[str]) -> None:
        """
        Items can be distinct_id or email
        Important! Does not insert into clickhouse
        """
        batchsize = 1000
        use_clickhouse = is_clickhouse_enabled()
        if use_clickhouse:
            from ee.clickhouse.models.cohort import insert_static_cohort
        try:
            cursor = connection.cursor()
            for i in range(0, len(items), batchsize):
                batch = items[i : i + batchsize]
                persons_query = (
                    Person.objects.filter(team_id=self.team_id)
                    .filter(Q(persondistinctid__team_id=self.team_id, persondistinctid__distinct_id__in=batch))
                    .exclude(cohort__id=self.id)
                )
                if use_clickhouse:
                    insert_static_cohort([p for p in persons_query.values_list("uuid", flat=True)], self.pk, self.team)
                sql, params = persons_query.distinct("pk").only("pk").query.sql_with_params()
                query = UPDATE_QUERY.format(
                    cohort_id=self.pk,
                    values_query=sql.replace('FROM "posthog_person"', f', {self.pk} FROM "posthog_person"', 1,),
                )
                cursor.execute(query, params)
            self.is_calculating = False
            self.last_calculation = timezone.now()
            self.errors_calculating = 0
            self.save()
        except Exception as err:
            if settings.DEBUG:
                raise err
            self.is_calculating = False
            self.errors_calculating = F("errors_calculating") + 1
            self.save()
            capture_exception(err)

    def insert_users_list_by_uuid(self, items: List[str]) -> None:
        batchsize = 1000
        try:
            cursor = connection.cursor()
            for i in range(0, len(items), batchsize):
                batch = items[i : i + batchsize]
                persons_query = (
                    Person.objects.filter(team_id=self.team_id).filter(uuid__in=batch).exclude(cohort__id=self.id)
                )
                sql, params = persons_query.distinct("pk").only("pk").query.sql_with_params()
                query = UPDATE_QUERY.format(
                    cohort_id=self.pk,
                    values_query=sql.replace('FROM "posthog_person"', f', {self.pk} FROM "posthog_person"', 1,),
                )
                cursor.execute(query, params)

            self.is_calculating = False
            self.last_calculation = timezone.now()
            self.errors_calculating = 0
            self.save()
        except Exception as err:
            if settings.DEBUG:
                raise err
            self.is_calculating = False
            self.errors_calculating = F("errors_calculating") + 1
            self.save()
            capture_exception(err)

    def __str__(self):
        return self.name

    def _clickhouse_persons_query(self):
        from ee.clickhouse.models.cohort import get_person_ids_by_cohort_id

        uuids = get_person_ids_by_cohort_id(team=self.team, cohort_id=self.pk)
        return Person.objects.filter(uuid__in=uuids, team=self.team)

    def _postgres_persons_query(self):
        return Person.objects.filter(self._people_filter(), team=self.team)

    def _people_filter(self, extra_filter=None):
        from posthog.queries.base import properties_to_Q

        filters = Q()
        for group in self.groups:
            if group.get("action_id"):
                action = Action.objects.get(pk=group["action_id"], team_id=self.team_id)
                events = (
                    Event.objects.filter_by_action(action)
                    .filter(
                        team_id=self.team_id,
                        **(
                            {"timestamp__gt": timezone.now() - relativedelta(days=int(group["days"]))}
                            if group.get("days")
                            else {}
                        ),
                        **(extra_filter if extra_filter else {}),
                    )
                    .order_by("distinct_id")
                    .distinct("distinct_id")
                    .values("distinct_id")
                )

                filters |= Q(persondistinctid__distinct_id__in=events)
            elif group.get("properties"):
                filter = Filter(data=group)
                filters |= Q(properties_to_Q(filter.properties, team_id=self.team_id, is_direct_query=True))
        return filters

    __repr__ = sane_repr("id", "name", "last_calculation")


class CohortPeople(models.Model):
    id: models.BigAutoField = models.BigAutoField(primary_key=True)
    cohort: models.ForeignKey = models.ForeignKey("Cohort", on_delete=models.CASCADE)
    person: models.ForeignKey = models.ForeignKey("Person", on_delete=models.CASCADE)

    class Meta:
        indexes = [
            models.Index(fields=["cohort_id", "person_id"]),
        ]
