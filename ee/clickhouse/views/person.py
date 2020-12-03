from rest_framework import request, response

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
        team = self.team
        person = Person.objects.get(team=team, pk=pk)
        # TODO: Probably won't need this after a while

        events = Event.objects.filter(team=team, distinct_id__in=person.distinct_ids)
        events.delete()
        delete_person(person.uuid, delete_events=True, team_id=team.pk)
        person.delete()
        return response.Response(status=204)
