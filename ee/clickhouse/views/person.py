from typing import Callable, Dict, Tuple, Union

from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.response import Response

from ee.clickhouse.models.person import delete_person
from ee.clickhouse.queries.clickhouse_retention import ClickhouseRetention
from ee.clickhouse.queries.clickhouse_stickiness import ClickhouseStickiness
from ee.clickhouse.queries.funnels import ClickhouseFunnelPersons, ClickhouseFunnelTrendsPersons
from ee.clickhouse.queries.trends.lifecycle import ClickhouseLifecycle
from posthog.api.person import PersonViewSet
from posthog.api.utils import format_next_absolute_url, format_next_url
from posthog.constants import INSIGHT_FUNNELS, FunnelType
from posthog.decorators import cached_function
from posthog.models import Event, Filter, Person


# TODO: Move grabbing all this to Clickhouse. See WIP-people-from-clickhouse branch.
# TODO: wut, can I remove this TODO? TODO recurse.
class ClickhousePersonViewSet(PersonViewSet):

    lifecycle_class = ClickhouseLifecycle
    retention_class = ClickhouseRetention
    stickiness_class = ClickhouseStickiness

    # TODO: Why isn't POST allowed?? Test & check - request is symmetric with /api/insight/funnel
    @action(methods=["GET"], detail=False)
    def funnel(self, request: Request, **kwargs) -> Response:
        if request.user.is_anonymous or not request.user.team:
            return Response(data=[])

        results, next_url = self.calculate_funnel_persons(request)["result"]

        return Response(data={"results": results, "next": next_url})

    @cached_function()
    def calculate_funnel_persons(self, request: Request) -> Dict[str, Tuple[list, str]]:
        team = request.user.team
        filter = Filter(request=request)
        funnel_class: Callable = ClickhouseFunnelPersons

        if filter.funnel_type == FunnelType.TRENDS:
            funnel_class = ClickhouseFunnelTrendsPersons
        # elif filter.funnel_type == FunnelType.UNORDERED:
        #     funnel_class = ClickhouseFunnelUnorderedPersons

        results = funnel_class(filter, team).run()
        next_url = format_next_absolute_url(request, filter.offset, 100) if len(results) > 99 else None

        # cached_function expects a dict with the key result
        return {"result": (results, next_url)}

    def destroy(self, request: Request, pk=None, **kwargs):  # type: ignore
        try:
            person = Person.objects.get(team=self.team, pk=pk)

            events = Event.objects.filter(team=self.team, distinct_id__in=person.distinct_ids)
            events.delete()
            delete_person(
                person.uuid, person.properties, person.is_identified, delete_events=True, team_id=self.team.pk
            )
            person.delete()
            return Response(status=204)
        except Person.DoesNotExist:
            raise NotFound(detail="Person not found.")
