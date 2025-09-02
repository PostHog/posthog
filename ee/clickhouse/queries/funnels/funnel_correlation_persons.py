from typing import Optional, Union

from django.db.models.query import QuerySet

from rest_framework.exceptions import ValidationError

from posthog.constants import FUNNEL_CORRELATION_PERSON_LIMIT, FunnelCorrelationType, PropertyOperatorType
from posthog.models import Person
from posthog.models.entity import Entity
from posthog.models.filters.filter import Filter
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.group import Group
from posthog.models.team import Team
from posthog.queries.actor_base_query import ActorBaseQuery, SerializedGroup, SerializedPerson
from posthog.queries.funnels.funnel_event_query import FunnelEventQuery
from posthog.queries.util import get_person_properties_mode

from ee.clickhouse.queries.funnels.funnel_correlation import FunnelCorrelation


class FunnelCorrelationActors(ActorBaseQuery):
    _filter: Filter
    QUERY_TYPE = "funnel_correlation_actors"

    def __init__(self, filter: Filter, team: Team, base_uri: str = "/", **kwargs) -> None:
        self._base_uri = base_uri
        self._filter = filter
        self._team = team

        if not self._filter.correlation_person_limit:
            self._filter = self._filter.shallow_clone({FUNNEL_CORRELATION_PERSON_LIMIT: 100})

    @cached_property
    def aggregation_group_type_index(self):
        return self._filter.aggregation_group_type_index

    def actor_query(self, limit_actors: Optional[bool] = True):
        if self._filter.correlation_type == FunnelCorrelationType.PROPERTIES:
            return _FunnelPropertyCorrelationActors(self._filter, self._team, self._base_uri).actor_query(
                limit_actors=limit_actors
            )
        else:
            return _FunnelEventsCorrelationActors(self._filter, self._team, self._base_uri).actor_query(
                limit_actors=limit_actors
            )

    def get_actors(
        self,
    ) -> tuple[
        Union[QuerySet[Person], QuerySet[Group]],
        Union[list[SerializedGroup], list[SerializedPerson]],
        int,
    ]:
        if self._filter.correlation_type == FunnelCorrelationType.PROPERTIES:
            return _FunnelPropertyCorrelationActors(self._filter, self._team, self._base_uri).get_actors()
        else:
            return _FunnelEventsCorrelationActors(self._filter, self._team, self._base_uri).get_actors()


class _FunnelEventsCorrelationActors(ActorBaseQuery):
    _filter: Filter
    QUERY_TYPE = "funnel_events_correlation_actors"

    def __init__(self, filter: Filter, team: Team, base_uri: str = "/") -> None:
        self._funnel_correlation = FunnelCorrelation(filter, team, base_uri=base_uri)
        super().__init__(team, filter)

    @cached_property
    def aggregation_group_type_index(self):
        return self._filter.aggregation_group_type_index

    def actor_query(self, limit_actors: Optional[bool] = True):
        if not self._filter.correlation_person_entity:
            raise ValidationError("No entity for persons specified")

        assert isinstance(self._filter.correlation_person_entity, Entity)

        (
            funnel_persons_query,
            funnel_persons_params,
        ) = self._funnel_correlation.get_funnel_actors_cte()

        prop_filters = self._filter.correlation_person_entity.property_groups

        # TRICKY: We use "events" as an alias here while the eventquery uses "e" by default
        event_query = FunnelEventQuery(self._filter, self._team)
        event_query.EVENT_TABLE_ALIAS = "events"

        prop_query, prop_params = event_query._get_prop_groups(
            prop_filters,
            person_properties_mode=get_person_properties_mode(self._team),
            person_id_joined_alias=event_query._get_person_id_alias(self._team.person_on_events_mode),
        )

        conversion_filter = (
            f'AND actors.steps {"=" if self._filter.correlation_persons_converted else "<>"} target_step'
            if self._filter.correlation_persons_converted is not None
            else ""
        )

        event_join_query = self._funnel_correlation._get_events_join_query()

        recording_event_select_statement = (
            ", any(actors.matching_events) AS matching_events" if self._filter.include_recordings else ""
        )

        query = f"""
            WITH
                funnel_actors as ({funnel_persons_query}),
                toDateTime(%(date_to)s, %(timezone)s) AS date_to,
                toDateTime(%(date_from)s, %(timezone)s) AS date_from,
                %(target_step)s AS target_step,
                %(funnel_step_names)s as funnel_step_names
            SELECT
                actors.actor_id AS actor_id
                {recording_event_select_statement}
            FROM events AS event
                {event_join_query}
                AND event.event = %(target_event)s
                {conversion_filter}
                {prop_query}
            GROUP BY actor_id
            ORDER BY actor_id
            {"LIMIT %(limit)s" if limit_actors else ""}
            {"OFFSET %(offset)s" if limit_actors else ""}
        """

        params = {
            **funnel_persons_params,
            **prop_params,
            "target_event": self._filter.correlation_person_entity.id,
            "funnel_step_names": [entity.id for entity in self._filter.events],
            "target_step": len(self._filter.entities),
            "limit": self._filter.correlation_person_limit,
            "offset": self._filter.correlation_person_offset,
        }

        return query, params


class _FunnelPropertyCorrelationActors(ActorBaseQuery):
    _filter: Filter
    QUERY_TYPE = "funnel_property_correlation_actors"

    def __init__(self, filter: Filter, team: Team, base_uri: str = "/") -> None:
        # Filtering on persons / groups properties can be pushed down to funnel_actors CTE
        new_correlation_filter = filter.shallow_clone(
            {
                "properties": filter.property_groups.combine_properties(
                    PropertyOperatorType.AND, filter.correlation_property_values or []
                ).to_dict()
            }
        )
        self._funnel_correlation = FunnelCorrelation(new_correlation_filter, team, base_uri=base_uri)
        super().__init__(team, filter)

    @cached_property
    def aggregation_group_type_index(self):
        return self._filter.aggregation_group_type_index

    def actor_query(
        self,
        limit_actors: Optional[bool] = True,
        extra_fields: Optional[list[str]] = None,
    ):
        if not self._filter.correlation_property_values:
            raise ValidationError("Property Correlation expects atleast one Property to get persons for")

        (
            funnel_persons_query,
            funnel_persons_params,
        ) = self._funnel_correlation.get_funnel_actors_cte()

        conversion_filter = (
            f'funnel_actors.steps {"=" if self._filter.correlation_persons_converted else "<>"} target_step'
            if self._filter.correlation_persons_converted is not None
            else ""
        )

        recording_event_select_statement = (
            ", any(funnel_actors.matching_events) AS matching_events" if self._filter.include_recordings else ""
        )

        query = f"""
            WITH
                funnel_actors AS ({funnel_persons_query}),
                %(target_step)s AS target_step
            SELECT
                funnel_actors.actor_id AS actor_id
                {recording_event_select_statement}
            FROM funnel_actors
            WHERE {conversion_filter}
            GROUP BY funnel_actors.actor_id
            ORDER BY actor_id
            {"LIMIT %(limit)s" if limit_actors else ""}
            {"OFFSET %(offset)s" if limit_actors else ""}
        """
        params = {
            **funnel_persons_params,
            "target_step": len(self._filter.entities),
            "limit": self._filter.correlation_person_limit,
            "offset": self._filter.correlation_person_offset,
        }

        return query, params
