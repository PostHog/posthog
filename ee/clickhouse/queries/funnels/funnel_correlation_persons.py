from typing import Any, Dict, List, Optional, Tuple, Union, cast

from django.db.models.query import QuerySet
from rest_framework.exceptions import ValidationError
from rest_framework.utils.serializer_helpers import ReturnDict, ReturnList

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.property import get_property_string_expr
from ee.clickhouse.queries.actor_base_query import ActorBaseQuery, SerializedGroup, SerializedPerson
from ee.clickhouse.queries.column_optimizer import ColumnOptimizer
from ee.clickhouse.queries.funnels.funnel_correlation import FunnelCorrelation
from ee.clickhouse.queries.funnels.funnel_event_query import FunnelEventQuery
from ee.clickhouse.queries.person_query import ClickhousePersonQuery
from ee.clickhouse.sql.person import GET_TEAM_PERSON_DISTINCT_IDS
from posthog.constants import FUNNEL_CORRELATION_PERSON_LIMIT, FunnelCorrelationType
from posthog.models import Person
from posthog.models.entity import Entity
from posthog.models.filters.filter import Filter
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.group import Group
from posthog.models.team import Team


class FunnelCorrelationActors:
    def __init__(self, filter: Filter, team: Team, base_uri: str = "/") -> None:
        self._base_uri = base_uri
        self._filter = filter
        self._team = team

        if not self._filter.correlation_person_limit:
            self._filter = self._filter.with_data({FUNNEL_CORRELATION_PERSON_LIMIT: 100})

    def get_actors(
        self,
    ) -> Tuple[Union[QuerySet[Person], QuerySet[Group]], Union[List[SerializedGroup], List[SerializedPerson]]]:
        if self._filter.correlation_type == FunnelCorrelationType.PROPERTIES:
            return _FunnelPropertyCorrelationActors(self._filter, self._team, self._base_uri).get_actors()
        else:
            return _FunnelEventsCorrelationActors(self._filter, self._team, self._base_uri).get_actors()


class _FunnelEventsCorrelationActors(ActorBaseQuery):
    def __init__(self, filter: Filter, team: Team, base_uri: str = "/") -> None:
        self._funnel_correlation = FunnelCorrelation(filter, team, base_uri=base_uri)
        super().__init__(team, filter)

    @cached_property
    def is_aggregating_by_groups(self) -> bool:
        return self._filter.aggregation_group_type_index is not None

    def actor_query(self, extra_fields: Optional[List[str]] = None):

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


class _FunnelPropertyCorrelationActors(ActorBaseQuery):
    def __init__(self, filter: Filter, team: Team, base_uri: str = "/") -> None:
        self._funnel_correlation = FunnelCorrelation(filter, team, base_uri=base_uri)
        super().__init__(team, filter)

    @cached_property
    def is_aggregating_by_groups(self) -> bool:
        return self._filter.aggregation_group_type_index is not None

    def actor_query(self, extra_fields: Optional[List[str]] = None):
        if not self._filter.correlation_property_values:
            raise ValidationError("Property Correlation expects atleast one Property to get persons for")

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
            "target_step": len(self._filter.entities),
        }

        return query, params
