from typing import Optional
from uuid import uuid4

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.event import ClickhouseEventSerializer, create_event
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.sql.events import GET_EVENTS_WITH_PROPERTIES
from ee.clickhouse.util import ClickhouseTestMixin
from posthog.models.filter import Filter
from posthog.models.person import Person
from posthog.models.team import Team
from posthog.test.test_filter_model import property_to_Q_test_factory


def _filter_events(
    filter: Filter, team: Team, person_query: Optional[bool] = False, order_by: Optional[str] = None,
):
    prop_filters, prop_filter_params = parse_prop_clauses("uuid", filter.properties, team)
    params = {"team_id": team.pk ** prop_filter_params}
    events = sync_execute(
        GET_EVENTS_WITH_PROPERTIES.format(
            filters=prop_filters, order_by="ORDER BY {}".format(order_by) if order_by else "",
        ),
        params,
    )
    parsed_events = ClickhouseEventSerializer(events, many=True, context={"elements": None, "people": None}).data
    return parsed_events


def _create_person(**kwargs):
    person = Person.objects.create(**kwargs)
    return Person(id=person.uuid)


def _create_event(**kwargs):
    kwargs.update({"event_uuid": uuid4()})
    create_event(**kwargs)


class TestClickhouseFiltering(
    ClickhouseTestMixin, property_to_Q_test_factory(_filter_events, _create_event, _create_person),
):
    pass
