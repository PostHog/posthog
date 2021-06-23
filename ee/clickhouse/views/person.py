from rest_framework import request, response
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound

from ee.clickhouse.models.person import delete_person
from ee.clickhouse.queries.clickhouse_retention import ClickhouseRetention
from ee.clickhouse.queries.clickhouse_stickiness import ClickhouseStickiness
from ee.clickhouse.queries.funnels.funnel_persons import ClickhouseFunnelPersons
from ee.clickhouse.queries.funnels.funnel_trends_persons import ClickhouseFunnelTrendsPersons
from ee.clickhouse.queries.trends.lifecycle import ClickhouseLifecycle
from posthog.api.person import PersonViewSet
from posthog.api.utils import format_next_absolute_url, format_next_url
from posthog.models import Event, Filter, Person


# TODO: Move grabbing all this to Clickhouse. See WIP-people-from-clickhouse branch.
class ClickhousePersonViewSet(PersonViewSet):

    lifecycle_class = ClickhouseLifecycle
    retention_class = ClickhouseRetention
    stickiness_class = ClickhouseStickiness

    @action(methods=["GET"], detail=False)
    def funnel(self, request: request.Request, **kwargs) -> response.Response:
        if request.user.is_anonymous or not request.user.team:
            return response.Response(data=[])

        filter = Filter(request=request)
        team = request.user.team
        results = ClickhouseFunnelPersons(filter, team).run()

        next_url = format_next_absolute_url(request, filter.offset, 100) if len(results) > 99 else None
        return response.Response(data={"results": results, "next": next_url})

    @action(methods=["GET"], detail=False)
    def funnel_trends(self, request: request.Request, **kwargs) -> response.Response:
        if request.user.is_anonymous or not request.user.team:
            return response.Response(data=[])

        filter = Filter(request=request)
        team = request.user.team
        results = ClickhouseFunnelTrendsPersons(filter, team).run()

        next_url = format_next_absolute_url(request, filter.offset, 100) if len(results) > 99 else None
        return response.Response(data={"results": results, "next": next_url})

    def destroy(self, request: request.Request, pk=None, **kwargs):  # type: ignore
        try:
            person = Person.objects.get(team=self.team, pk=pk)

            events = Event.objects.filter(team=self.team, distinct_id__in=person.distinct_ids)
            events.delete()
            delete_person(
                person.uuid, person.properties, person.is_identified, delete_events=True, team_id=self.team.pk
            )
            person.delete()
            return response.Response(status=204)
        except Person.DoesNotExist:
            raise NotFound(detail="Person not found.")
