from typing import Any, Dict, List, Optional, Tuple, cast

from rest_framework.exceptions import ValidationError
from rest_framework.utils.serializer_helpers import ReturnDict, ReturnList

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.property import get_property_string_expr
from ee.clickhouse.queries.column_optimizer import ColumnOptimizer
from ee.clickhouse.queries.funnels.funnel_correlation import FunnelCorrelation
from ee.clickhouse.queries.funnels.funnel_event_query import FunnelEventQuery
from ee.clickhouse.queries.person_query import ClickhousePersonQuery
from ee.clickhouse.sql.person import GET_TEAM_PERSON_DISTINCT_IDS
from posthog.constants import FUNNEL_CORRELATION_PERSON_LIMIT, FunnelCorrelationType
from posthog.models import Person
from posthog.models.entity import Entity
from posthog.models.filters.filter import Filter
from posthog.models.team import Team


class FunnelCorrelationPersons:
    def __init__(self, filter: Filter, team: Team, base_uri: str = "/") -> None:
        self._funnel_correlation = FunnelCorrelation(filter, team, base_uri=base_uri)
        self._filter = filter
        self._team = team

        if not self._filter.correlation_person_limit:
            self._filter = self._filter.with_data({FUNNEL_CORRELATION_PERSON_LIMIT: 100})

    def run(self):
        """
        Returns `ReturnList` type, generated by `serializers.serialize`, which returns the Person model.
        """

        query, params = self.get_query()
        results: List[Tuple[str]] = sync_execute(query, params)

        return self._format_results(results)

    def get_query(self) -> Tuple[str, Dict[str, Any]]:
        if self._filter.correlation_type == FunnelCorrelationType.PROPERTIES:
            return self.get_properties_query()

        else:
            return self.get_events_query()

    def get_properties_query(self) -> Tuple[str, Dict[str, Any]]:

        if not self._filter.correlation_property_values:
            raise ValidationError("Property Correlation expects atleast one Property Value pair to get persons for")

        if len(self._filter.correlation_property_names) != len(self._filter.correlation_property_values):
            raise ValidationError("Property Correlation persons expects same number of Property names and values")

        funnel_persons_query, funnel_persons_params = self._funnel_correlation.get_funnel_persons_cte()

        conversion_filter = (
            f'funnel_people.steps {"=" if self._filter.correlation_persons_converted else "<>"} target_step'
            if self._filter.correlation_persons_converted is not None
            else ""
        )

        person_query, person_query_params = ClickhousePersonQuery(
            self._filter,
            self._team.pk,
            entity=Entity({"id": "person", "type": "events", "properties": self._filter.correlation_property_values}),
        ).get_query()

        query = f"""
            WITH
                funnel_people as ({funnel_persons_query}),
                %(target_step)s AS target_step
            SELECT
                DISTINCT funnel_people.person_id as person_id
            FROM funnel_people
            JOIN ({person_query}) person
                ON person.id = funnel_people.person_id
            WHERE {conversion_filter}
            ORDER BY person_id
            LIMIT {self._filter.correlation_person_limit}
            OFFSET {self._filter.correlation_person_offset}
        """
        params = {
            **funnel_persons_params,
            **person_query_params,
            # **person_property_params,
            "target_step": len(self._filter.entities),
        }

        return query, params

    def get_events_query(self) -> Tuple[str, Dict[str, Any]]:

        if not self._filter.correlation_person_entity:
            raise ValidationError("No entity for persons specified")

        assert isinstance(self._filter.correlation_person_entity, Entity)

        funnel_persons_query, funnel_persons_params = self._funnel_correlation.get_funnel_persons_cte()

        prop_filters = self._filter.correlation_person_entity.properties
        prop_query, prop_params = FunnelEventQuery(self._filter, self._team.pk)._get_props(prop_filters)

        conversion_filter = (
            f'AND person.steps {"=" if self._filter.correlation_persons_converted else "<>"} target_step'
            if self._filter.correlation_persons_converted is not None
            else ""
        )

        event_join_query = self._funnel_correlation._get_events_join_query()

        query = f"""
            WITH
                funnel_people as ({funnel_persons_query}),
                toDateTime(%(date_to)s) AS date_to,
                toDateTime(%(date_from)s) AS date_from,
                %(target_step)s AS target_step,
                %(funnel_step_names)s as funnel_step_names
            SELECT
                DISTINCT person.person_id as person_id
            FROM events AS event
                {event_join_query}
                AND event.event = %(target_event)s
                {conversion_filter}
                {prop_query}
            ORDER BY person_id
            LIMIT {self._filter.correlation_person_limit}
            OFFSET {self._filter.correlation_person_offset}
        """

        params = {
            **funnel_persons_params,
            **prop_params,
            "target_event": self._filter.correlation_person_entity.id,
            "funnel_step_names": [entity.id for entity in self._filter.events],
            "target_step": len(self._filter.entities),
        }

        return query, params

    def _format_results(self, results: List[Tuple[str]]):
        people = Person.objects.filter(team_id=self._team.pk, uuid__in=[val[0] for val in results])

        from posthog.api.person import PersonSerializer

        return (
            PersonSerializer(people, many=True).data,
            len(results) > cast(int, self._filter.correlation_person_limit) - 1,
        )
