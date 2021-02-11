from rest_framework import request, response
from rest_framework.exceptions import NotFound

from ee.clickhouse.models.person import delete_person
from ee.clickhouse.queries.clickhouse_retention import ClickhouseRetention
from ee.clickhouse.queries.clickhouse_stickiness import ClickhouseStickiness
from ee.clickhouse.queries.trends.lifecycle import ClickhouseLifecycle
from posthog.api.person import PersonViewSet
from posthog.models import Event, Person


# TODO: Move grabbing all this to Clickhouse. See WIP-people-from-clickhouse branch.
class ClickhousePersonViewSet(PersonViewSet):

    lifecycle_class = ClickhouseLifecycle
    retention_class = ClickhouseRetention
    stickiness_class = ClickhouseStickiness

    def destroy(self, request: request.Request, pk=None, **kwargs):  # type: ignore
        try:
            person = Person.objects.get(team=self.team, pk=pk)

            events = Event.objects.filter(team=self.team, distinct_id__in=person.distinct_ids)
            events.delete()
            delete_person(person.uuid, delete_events=True, team_id=self.team.pk)
            person.delete()
            return response.Response(status=204)
        except Person.DoesNotExist:
            raise NotFound(detail="Person not found.")
