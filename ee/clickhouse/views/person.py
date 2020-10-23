import json
from typing import List

from rest_framework import request, response

from ee.clickhouse.models.person import delete_person
from ee.clickhouse.util import CH_PERSON_ENDPOINT, endpoint_enabled
from posthog.api.person import PersonViewSet
from posthog.models import Event, Person


# TODO: Move grabbing all this to Clickhouse. See WIP-people-from-clickhouse branch.
class ClickhousePerson(PersonViewSet):
    def destroy(self, request: request.Request, pk=None):  # type: ignore
        team = request.user.team
        person = Person.objects.get(team=team, pk=pk)
        # TODO: Probably won't need this after a while

        events = Event.objects.filter(team=team, distinct_id__in=person.distinct_ids)
        events.delete()
        delete_person(person.uuid, delete_events=True, team_id=team.pk)
        person.delete()
        return response.Response(status=204)
