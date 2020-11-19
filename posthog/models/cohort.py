import json
from typing import Any, Dict, Optional

from dateutil.relativedelta import relativedelta
from django.contrib.postgres.fields import JSONField
from django.db import connection, models, transaction
from django.db.models import Q
from django.utils import timezone
from sentry_sdk import capture_exception

from posthog.ee import is_ee_enabled

from .action import Action
from .event import Event
from .filter import Filter
from .person import Person

UPDATE_QUERY = """
DELETE FROM "posthog_cohortpeople" WHERE "cohort_id" = {cohort_id};
INSERT INTO "posthog_cohortpeople" ("person_id", "cohort_id")
{values_query}
ON CONFLICT DO NOTHING
"""


class Group(object):
    def __init__(
        self, properties: Optional[Dict[str, Any]] = None, action_id: Optional[int] = None, days: Optional[int] = None,
    ):
        if not properties and not action_id:
            raise ValueError("Cohort group needs properties or action_id")
        self.properties = properties
        self.action_id = action_id
        self.days = days


class CohortManager(models.Manager):
    def create(self, *args: Any, **kwargs: Any):
        kwargs["groups"] = [Group(**group).__dict__ for group in kwargs["groups"]]
        cohort = super().create(*args, **kwargs)
        return cohort


class Cohort(models.Model):
    name: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    deleted: models.BooleanField = models.BooleanField(default=False)
    groups: JSONField = JSONField(default=list)
    people: models.ManyToManyField = models.ManyToManyField("Person", through="CohortPeople")

    created_by: models.ForeignKey = models.ForeignKey("User", on_delete=models.SET_NULL, blank=True, null=True)
    created_at: models.DateTimeField = models.DateTimeField(default=timezone.now, blank=True, null=True)
    is_calculating: models.BooleanField = models.BooleanField(default=False)
    last_calculation: models.DateTimeField = models.DateTimeField(blank=True, null=True)

    objects = CohortManager()

    def calculate_people(self, use_clickhouse=is_ee_enabled()):
        try:
            if not use_clickhouse:
                self.is_calculating = True
                self.save()

            persons_query = self._clickhouse_persons_query() if use_clickhouse else self._postgres_persons_query()
            sql, params = persons_query.distinct("pk").only("pk").query.sql_with_params()

            query = UPDATE_QUERY.format(
                cohort_id=self.pk,
                values_query=sql.replace('FROM "posthog_person"', ', {} FROM "posthog_person"'.format(self.pk), 1,),
            )

            cursor = connection.cursor()
            with transaction.atomic():
                cursor.execute(query, params)

                self.is_calculating = False
                self.last_calculation = timezone.now()
                self.save()
        except:
            capture_exception()

    def __str__(self):
        return self.name

    def _clickhouse_persons_query(self):
        from ee.clickhouse.models.cohort import get_person_ids_by_cohort_id

        uuids = get_person_ids_by_cohort_id(team=self.team, cohort_id=self.pk)
        return Person.objects.filter(uuid__in=uuids, team=self.team)

    def _postgres_persons_query(self):
        return Person.objects.filter(self._people_filter(), team=self.team)

    def _people_filter(self, extra_filter=None):
        filters = Q()
        for group in self.groups:
            if group.get("action_id"):
                action = Action.objects.get(pk=group["action_id"], team_id=self.team_id)
                events = (
                    Event.objects.filter_by_action(action)
                    .filter(
                        team_id=self.team_id,
                        **(
                            {"timestamp__gt": timezone.now() - relativedelta(days=group["days"])}
                            if group.get("days")
                            else {}
                        ),
                        **(extra_filter if extra_filter else {})
                    )
                    .order_by("distinct_id")
                    .distinct("distinct_id")
                    .values("distinct_id")
                )

                filters |= Q(persondistinctid__distinct_id__in=events)
            elif group.get("properties"):
                filter = Filter(data=group)
                filters |= Q(filter.properties_to_Q(team_id=self.team_id, is_person_query=True))
        return filters


class CohortPeople(models.Model):
    id: models.BigAutoField = models.BigAutoField(primary_key=True)
    cohort: models.ForeignKey = models.ForeignKey("Cohort", on_delete=models.CASCADE)
    person: models.ForeignKey = models.ForeignKey("Person", on_delete=models.CASCADE)

    class Meta:
        indexes = [
            models.Index(fields=["cohort_id", "person_id"]),
        ]
