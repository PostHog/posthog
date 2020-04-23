from django.db import models
from django.db.models import Q
from .person import Person
from .action import Action
from .event import Event
from posthog.utils import properties_to_Q
from django.utils import timezone
from django.contrib.postgres.fields import JSONField
from dateutil.relativedelta import relativedelta


class Cohort(models.Model):
    @property
    def people(self):
        return Person.objects.filter(self.people_filter, team=self.team_id)

    @property
    def people_filter(self):
        filters = Q()
        for group in self.groups:
            if group.get("action_id"):
                action = Action.objects.get(pk=group["action_id"], team_id=self.team_id)
                events = (
                    Event.objects.filter_by_action(action)
                    .filter(
                        team_id=self.team_id,
                        **(
                            {
                                "timestamp__gt": timezone.now()
                                - relativedelta(days=group["days"])
                            }
                            if group.get("days")
                            else {}
                        )
                    )
                    .order_by("distinct_id")
                    .distinct("distinct_id")
                    .values("distinct_id")
                )

                filters |= Q(persondistinctid__distinct_id__in=events)
            elif group.get("properties"):
                properties = properties_to_Q(group["properties"])
                filters |= Q(properties)
        return filters

    name: models.CharField = models.CharField(max_length=400, null=True, blank=True)
    team: models.ForeignKey = models.ForeignKey("Team", on_delete=models.CASCADE)
    deleted: models.BooleanField = models.BooleanField(default=False)
    groups: JSONField = JSONField(default=list)
