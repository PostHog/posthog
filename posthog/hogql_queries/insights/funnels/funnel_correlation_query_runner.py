import dataclasses
from typing import Any, Literal, Optional, TypedDict, cast

from rest_framework.exceptions import ValidationError

from posthog.schema import (
    ActionsNode,
    CachedFunnelCorrelationResponse,
    CorrelationType,
    EventDefinition,
    EventOddsRatioSerialized,
    EventsNode,
    FunnelCorrelationActorsQuery,
    FunnelCorrelationQuery,
    FunnelCorrelationResponse,
    FunnelCorrelationResult,
    FunnelCorrelationResultsType,
    FunnelsActorsQuery,
    FunnelsQuery,
    HogQLQueryModifiers,
    HogQLQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.parser import parse_select
from posthog.hogql.printer import to_printed_hogql
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.timings import HogQLTimings

from posthog.constants import AUTOCAPTURE_EVENT
from posthog.hogql_queries.insights.funnels import FunnelUDF
from posthog.hogql_queries.insights.funnels.funnel_event_query import FunnelEventQuery
from posthog.hogql_queries.insights.funnels.funnel_persons import FunnelActors
from posthog.hogql_queries.insights.funnels.funnel_query_context import FunnelQueryContext
from posthog.hogql_queries.insights.funnels.funnel_strict_actors import FunnelStrictActors
from posthog.hogql_queries.insights.funnels.funnel_unordered_actors import FunnelUnorderedActors
from posthog.hogql_queries.insights.funnels.utils import (
    funnel_window_interval_unit_to_sql,
    get_funnel_actor_class,
    use_udf,
)
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.models import Team
from posthog.models.action.action import Action
from posthog.models.element.element import chain_to_elements
from posthog.models.event.util import ElementSerializer
from posthog.models.property.util import get_property_string_expr
from posthog.queries.util import correct_result_for_sampling


class EventOddsRatio(TypedDict):
    event: str

    success_count: int
    failure_count: int

    odds_ratio: float
    correlation_type: Literal["success", "failure"]


@dataclasses.dataclass
class EventStats:
    success_count: int
    failure_count: int


@dataclasses.dataclass
class EventContingencyTable:
    """
    Represents a contingency table for a single event. Note that this isn't a
    complete contingency table, but rather only includes totals for
    failure/success as opposed to including the number of successes for cases
    that a persons _doesn't_ visit an event.
    """

    event: str
    visited: EventStats

    success_total: int
    failure_total: int


PRIOR_COUNT = 1


class FunnelCorrelationQueryRunner(AnalyticsQueryRunner[FunnelCorrelationResponse]):
    TOTAL_IDENTIFIER = "Total_Values_In_Query"
    ELEMENTS_DIVIDER = "__~~__"
    AUTOCAPTURE_EVENT_TYPE = "$event_type"
    MIN_PERSON_COUNT = 25
    MIN_PERSON_PERCENTAGE = 0.02

    query: FunnelCorrelationQuery
    cached_response: CachedFunnelCorrelationResponse

    funnels_query: FunnelsQuery
    actors_query: FunnelsActorsQuery
    correlation_actors_query: Optional[FunnelCorrelationActorsQuery]

    _funnel_actors_generator: FunnelActors | FunnelStrictActors | FunnelUnorderedActors | FunnelUDF

    def __init__(
        self,
        query: FunnelCorrelationQuery | dict[str, Any],
        team: Team,
        timings: Optional[HogQLTimings] = None,
        modifiers: Optional[HogQLQueryModifiers] = None,
        limit_context: Optional[LimitContext] = None,
    ):
        super().__init__(query, team=team, timings=timings, modifiers=modifiers, limit_context=limit_context)
        self.actors_query = self.query.source
        self.funnels_query = self.actors_query.source

        # Funnel Step by default set to 1, to give us all people who entered the funnel
        if self.actors_query.funnelStep is None:
            self.actors_query.funnelStep = 1

        self.context = FunnelQueryContext(
            query=self.funnels_query,
            team=team,
            timings=timings,
            modifiers=modifiers,
            limit_context=limit_context,
            # NOTE: we want to include the latest timestamp of the `target_step`,
            # from this we can deduce if the person reached the end of the funnel,
            # i.e. successful
            include_timestamp=True,
            # NOTE: we don't need these as we have all the information we need to
            # deduce if the person was successful or not
            include_preceding_timestamp=False,
            include_properties=self.properties_to_include,
            # NOTE: we always use the final matching event for the recording because this
            # is the the right event for both drop off and successful funnels
            include_final_matching_events=self.actors_query.includeRecordings,
        )
        self.context.actorsQuery = self.actors_query

        # Used for generating the funnel persons cte
        funnel_order_actor_class = get_funnel_actor_class(
            self.context.funnelsFilter, use_udf(self.context.funnelsFilter, self.team)
        )(context=self.context)
        assert isinstance(
            funnel_order_actor_class, FunnelActors | FunnelStrictActors | FunnelUnorderedActors | FunnelUDF
        )  # for typings
        self._funnel_actors_generator = funnel_order_actor_class

    def _calculate(self) -> FunnelCorrelationResponse:
        """
        Funnel Correlation queries take as input the same as the funnel query,
        and returns the correlation of person events with a person successfully
        getting to the end of the funnel. We use Odds Ratios as the correlation
        metric. See https://en.wikipedia.org/wiki/Odds_ratio for more details.

        Roughly speaking, to calculate the odds ratio, we build a contingency
        table https://en.wikipedia.org/wiki/Contingency_table for each
        dimension, then calculate the odds ratio for each.

        For example, take for simplicity the cohort of all people, and the
        success criteria of having a "signed up" event. First we would build a
        contingency table like:

        |                    | success | failure | total |
        | -----------------: | :-----: | :-----: | :---: |
        | watched video      |    5    |    1    |   6   |
        | didn't watch video |    2    |   10    |   12  |


        Then the odds that a person signs up given they watched the video is 5 /
        1.

        And the odds that a person signs up given they didn't watch the video is
        2 / 10.

        So we say the odds ratio is 5 / 1 over 2 / 10 = 25 . The further away the
        odds ratio is from 1, the greater the correlation.

        Requirements:

         - Intitially we only need to consider the names of events that a cohort
           person has emitted. So we explicitly are not interested in e.g.
           correlating properties, although this will be a follow-up.

        Non-functional requirements:

         - there can be perhaps millions of people in a cohort, so we should
           consider this when writing the algorithm. e.g. we should probably
           avoid pulling all people into across the wire.
         - there can be an order of magnitude more events than people, so we
           should avoid pulling all events across the wire.
         - there may be a large but not huge number of distinct events, let's say
           100 different names for events. We should avoid n+1 queries for the
           event names dimension

        Contincency tables are something we can pull out of the db, so we can
        have a query that:

         1. filters people by the cohort criteria
         2. groups these people by the success criteria
         3. groups people by our criterion with which we want to test
            correlation, e.g. "watched video"

        --

        For each event a person that started going through the funnel, gets stats
        for how many of these users are sucessful and how many are unsuccessful.

        It's a partial table as it doesn't include numbers of the negation of the
        event, but does include the total success/failure numbers, which is enough
        for us to calculate the odds ratio.
        """
        if not self.funnels_query.series:
            return FunnelCorrelationResponse(
                results=FunnelCorrelationResult(events=[], skewed=False), modifiers=self.modifiers
            )

        events, skewed_totals, hogql, response = self._calculate_internal()

        return FunnelCorrelationResponse(
            results=FunnelCorrelationResult(
                events=[self.serialize_event_odds_ratio(odds_ratio=odds_ratio) for odds_ratio in events],
                skewed=skewed_totals,
            ),
            timings=response.timings,
            hogql=hogql,
            columns=response.columns,
            types=response.types,
            hasMore=response.hasMore,
            limit=response.limit,
            offset=response.offset,
            modifiers=self.modifiers,
        )

    def _calculate_internal(self) -> tuple[list[EventOddsRatio], bool, str, HogQLQueryResponse]:
        query = self.to_query()

        hogql = to_printed_hogql(query, self.team)

        response = execute_hogql_query(
            query_type="FunnelsQuery",
            query=query,
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
        )
        assert response.results

        # Get the total success/failure counts from the results
        results = [result for result in response.results if result[0] != self.TOTAL_IDENTIFIER]
        _, success_total, failure_total = next(
            result for result in response.results if result[0] == self.TOTAL_IDENTIFIER
        )

        # Add a little structure, and keep it close to the query definition so it's
        # obvious what's going on with result indices.
        event_contingency_tables = [
            EventContingencyTable(
                event=result[0],
                visited=EventStats(success_count=result[1], failure_count=result[2]),
                success_total=success_total,
                failure_total=failure_total,
            )
            for result in results
        ]

        success_total = int(correct_result_for_sampling(success_total, self.funnels_query.samplingFactor))
        failure_total = int(correct_result_for_sampling(failure_total, self.funnels_query.samplingFactor))

        if not success_total or not failure_total:
            return [], True, hogql, response

        skewed_totals = False

        # If the ratio is greater than 1:10, then we have a skewed result, so we should
        # warn the user.
        if success_total / failure_total > 10 or failure_total / success_total > 10:
            skewed_totals = True

        odds_ratios = [
            get_entity_odds_ratio(event_stats, PRIOR_COUNT)
            for event_stats in event_contingency_tables
            if not self.are_results_insignificant(event_stats)
        ]

        positively_correlated_events = sorted(
            [odds_ratio for odds_ratio in odds_ratios if odds_ratio["correlation_type"] == "success"],
            key=lambda x: x["odds_ratio"],
            reverse=True,
        )

        negatively_correlated_events = sorted(
            [odds_ratio for odds_ratio in odds_ratios if odds_ratio["correlation_type"] == "failure"],
            key=lambda x: x["odds_ratio"],
            reverse=False,
        )

        # Return the top ten positively correlated events, and top then negatively correlated events
        events = positively_correlated_events[:10] + negatively_correlated_events[:10]
        return events, skewed_totals, hogql, response

    def serialize_event_odds_ratio(self, odds_ratio: EventOddsRatio) -> EventOddsRatioSerialized:
        event_definition = self.serialize_event_with_property(event=odds_ratio["event"])
        return EventOddsRatioSerialized(
            success_count=odds_ratio["success_count"],
            failure_count=odds_ratio["failure_count"],
            odds_ratio=odds_ratio["odds_ratio"],
            correlation_type=(
                CorrelationType.SUCCESS if odds_ratio["correlation_type"] == "success" else CorrelationType.FAILURE
            ),
            event=event_definition,
        )

    def serialize_event_with_property(self, event: str) -> EventDefinition:
        """
        Format the event name for display.
        """
        if not self.support_autocapture_elements():
            return EventDefinition(event=event, properties={}, elements=[])

        event_name, property_name, property_value = event.split("::")
        if event_name == AUTOCAPTURE_EVENT and property_name == "elements_chain":
            event_type, elements_chain = property_value.split(self.ELEMENTS_DIVIDER)
            return EventDefinition(
                event=event,
                properties={self.AUTOCAPTURE_EVENT_TYPE: event_type},
                elements=cast(
                    list,
                    ElementSerializer(chain_to_elements(elements_chain), many=True).data,
                ),
            )

        return EventDefinition(event=event, properties={}, elements=[])

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        """
        Returns a query string and params, which are used to generate the contingency table.
        The query returns success and failure count for event / property values, along with total success and failure counts.
        """
        if self.query.funnelCorrelationType == FunnelCorrelationResultsType.PROPERTIES:
            return self.get_properties_query()

        if self.query.funnelCorrelationType == FunnelCorrelationResultsType.EVENT_WITH_PROPERTIES:
            return self.get_event_property_query()

        return self.get_event_query()

    def to_actors_query(self) -> ast.SelectQuery:
        assert self.correlation_actors_query is not None

        if self.query.funnelCorrelationType == FunnelCorrelationResultsType.PROPERTIES:
            # Filtering on persons / groups properties can be pushed down to funnel events query
            if (
                self.correlation_actors_query.funnelCorrelationPropertyValues
                and len(self.correlation_actors_query.funnelCorrelationPropertyValues) > 0
            ):
                self.context.query.properties = [
                    *(self.context.query.properties or []),
                    *self.correlation_actors_query.funnelCorrelationPropertyValues,
                ]
            return self.properties_actor_query()
        else:
            return self.events_actor_query()

    def events_actor_query(self) -> ast.SelectQuery:
        assert self.correlation_actors_query is not None

        if not self.correlation_actors_query.funnelCorrelationPersonEntity:
            raise ValidationError("No entity for persons specified")

        assert isinstance(self.correlation_actors_query.funnelCorrelationPersonEntity, EventsNode)

        target_step = self.context.max_steps
        target_event = self.correlation_actors_query.funnelCorrelationPersonEntity.event
        funnel_step_names = self._get_funnel_step_names()
        funnel_persons_query = self.get_funnel_actors_cte()
        funnel_event_query = FunnelEventQuery(context=self.context)
        date_from = funnel_event_query._date_range().date_from_as_hogql()
        date_to = funnel_event_query._date_range().date_to_as_hogql()

        properties = self.correlation_actors_query.funnelCorrelationPersonEntity.properties
        prop_query = None
        if properties is not None and properties != []:
            prop_query = property_to_expr(properties, self.team)

        conversion_filter = (
            f'AND funnel_actors.steps {"=" if self.correlation_actors_query.funnelCorrelationPersonConverted else "<>"} target_step'
            if self.correlation_actors_query.funnelCorrelationPersonConverted is not None
            else ""
        )

        event_join_query = self._get_events_join_query()

        recording_event_select_statement = (
            ", any(funnel_actors.matching_events) AS matching_events" if self.actors_query.includeRecordings else ""
        )

        query = parse_select(
            f"""
            WITH
                funnel_actors as (
                    {{funnel_persons_query}}
                ),
                {{date_from}} AS date_from,
                {{date_to}} AS date_to,
                {target_step} AS target_step,
                {funnel_step_names} AS funnel_step_names
            SELECT
                funnel_actors.actor_id AS actor_id
                {recording_event_select_statement}
            FROM events AS event
                {event_join_query}
                AND event.event = '{target_event}'
                {conversion_filter}
            GROUP BY actor_id
            ORDER BY actor_id
        """,
            placeholders={
                "funnel_persons_query": funnel_persons_query,
                "date_from": date_from,
                "date_to": date_to,
            },
        )
        assert isinstance(query, ast.SelectQuery)

        if prop_query:
            assert isinstance(query.where, ast.And)
            query.where.exprs = [*query.where.exprs, prop_query]

        return query

    def properties_actor_query(
        self,
    ) -> ast.SelectQuery:
        assert self.correlation_actors_query is not None

        if not self.correlation_actors_query.funnelCorrelationPropertyValues:
            raise ValidationError("Property Correlation expects atleast one Property to get persons for")

        target_step = self.context.max_steps
        funnel_persons_query = self.get_funnel_actors_cte()

        conversion_filter = (
            f'funnel_actors.steps {"=" if self.correlation_actors_query.funnelCorrelationPersonConverted else "<>"} target_step'
            if self.correlation_actors_query.funnelCorrelationPersonConverted is not None
            else ""
        )

        recording_event_select_statement = (
            ", any(funnel_actors.matching_events) AS matching_events" if self.actors_query.includeRecordings else ""
        )

        query = parse_select(
            f"""
            WITH
                funnel_actors as (
                    {{funnel_persons_query}}
                ),
                {target_step} AS target_step
            SELECT
                funnel_actors.actor_id AS actor_id
                {recording_event_select_statement}
            FROM funnel_actors
            WHERE {conversion_filter}
            GROUP BY funnel_actors.actor_id
            ORDER BY funnel_actors.actor_id
        """,
            placeholders={"funnel_persons_query": funnel_persons_query},
        )
        assert isinstance(query, ast.SelectQuery)

        return query

    def get_event_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        funnel_persons_query = self.get_funnel_actors_cte()
        event_join_query = self._get_events_join_query()
        target_step = self.context.max_steps
        funnel_step_names = self._get_funnel_step_names()
        funnel_event_query = FunnelEventQuery(context=self.context)
        date_from = funnel_event_query._date_range().date_from_as_hogql()
        date_to = funnel_event_query._date_range().date_to_as_hogql()

        event_correlation_query = parse_select(
            f"""
            WITH
                funnel_actors AS (
                    {{funnel_persons_query}}
                ),
                {{date_from}} AS date_from,
                {{date_to}} AS date_to,
                {target_step} AS target_step,
                {funnel_step_names} AS funnel_step_names

            SELECT
                event.event AS name,

                -- If we have a `person.steps = target_step`, we know the person
                -- reached the end of the funnel
                countDistinctIf(
                    funnel_actors.actor_id,
                    funnel_actors.steps = target_step
                ) AS success_count,

                -- And the converse being for failures
                countDistinctIf(
                    funnel_actors.actor_id,
                    funnel_actors.steps <> target_step
                ) AS failure_count

            FROM events AS event
                {event_join_query}
                AND event.event NOT IN {self.query.funnelCorrelationExcludeEventNames or []}
            GROUP BY name

            -- To get the total success/failure numbers, we do an aggregation on
            -- the funnel people CTE and count distinct actor_ids
            UNION ALL

            -- :HACKY: HogQL does not have access to a CTE in the second union query, thus
            -- we're repeating the CTE here. This likely is a big hit on query performance.
            WITH
                funnel_actors AS (
                    {{funnel_persons_query}}
                ),
                {target_step} AS target_step

            SELECT
                -- We're not using WITH TOTALS because the resulting queries are
                -- not runnable in Metabase
                '{self.TOTAL_IDENTIFIER}' as name,

                countDistinctIf(
                    funnel_actors.actor_id,
                    funnel_actors.steps = target_step
                ) AS success_count,

                countDistinctIf(
                    funnel_actors.actor_id,
                    funnel_actors.steps <> target_step
                ) AS failure_count
            FROM funnel_actors
        """,
            placeholders={
                "funnel_persons_query": funnel_persons_query,
                "date_from": date_from,
                "date_to": date_to,
            },
        )

        return event_correlation_query

    def get_event_property_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        if not self.query.funnelCorrelationEventNames:
            raise ValidationError("Event Property Correlation expects atleast one event name to run correlation on")

        funnel_persons_query = self.get_funnel_actors_cte()
        event_join_query = self._get_events_join_query()
        target_step = self.context.max_steps
        funnel_step_names = self._get_funnel_step_names()
        funnel_event_query = FunnelEventQuery(context=self.context)
        date_from = funnel_event_query._date_range().date_from_as_hogql()
        date_to = funnel_event_query._date_range().date_to_as_hogql()
        event_names = self.query.funnelCorrelationEventNames
        exclude_property_names = self.query.funnelCorrelationEventExcludePropertyNames or []

        if self.support_autocapture_elements():
            event_type_expression, _ = get_property_string_expr(
                "events",
                self.AUTOCAPTURE_EVENT_TYPE,
                f"'{self.AUTOCAPTURE_EVENT_TYPE}'",
                "properties",
                allow_denormalized_props=False,
            )
            array_join_query = f"""
                'elements_chain' as prop_key,
                concat({event_type_expression}, '{self.ELEMENTS_DIVIDER}', elements_chain) as prop_value,
                tuple(prop_key, prop_value) as prop
            """
        else:
            array_join_query = f"""
                arrayJoin(JSONExtractKeysAndValues(properties, 'String')) as prop
            """

        query = parse_select(
            f"""
            WITH
                funnel_actors AS (
                    {{funnel_persons_query}}
                ),
                {{date_from}} AS date_from,
                {{date_to}} AS date_to,
                {target_step} AS target_step,
                {funnel_step_names} AS funnel_step_names

            SELECT concat(event_name, '::', prop.1, '::', prop.2) as name,
                   countDistinctIf(actor_id, steps = target_step) as success_count,
                   countDistinctIf(actor_id, steps <> target_step) as failure_count
            FROM (
                SELECT
                    funnel_actors.actor_id as actor_id,
                    funnel_actors.steps as steps,
                    event.event as event_name,
                    -- Same as what we do in $all property queries
                    {array_join_query}
                FROM events AS event
                    {event_join_query}
                    AND event.event IN {event_names}
            )
            GROUP BY name, prop
            -- Discard high cardinality / low hits properties
            -- This removes the long tail of random properties with empty, null, or very small values
            HAVING (success_count + failure_count) > 2
            AND prop.1 NOT IN {exclude_property_names}

            UNION ALL
            -- To get the total success/failure numbers, we do an aggregation on
            -- the funnel people CTE and count distinct actor_ids

            -- :HACKY: HogQL does not have access to a CTE in the second union query, thus
            -- we're repeating the CTE here. This likely is a big hit on query performance.
            WITH
                funnel_actors AS (
                    {{funnel_persons_query}}
                ),
                {target_step} AS target_step

            SELECT
                '{self.TOTAL_IDENTIFIER}' as name,

                countDistinctIf(
                    funnel_actors.actor_id,
                    funnel_actors.steps = target_step
                ) AS success_count,

                countDistinctIf(
                    funnel_actors.actor_id,
                    funnel_actors.steps <> target_step
                ) AS failure_count
            FROM funnel_actors
        """,
            placeholders={
                "funnel_persons_query": funnel_persons_query,
                "date_from": date_from,
                "date_to": date_to,
            },
        )

        return query

    def get_properties_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        if not self.query.funnelCorrelationNames:
            raise ValidationError("Property Correlation expects atleast one Property to run correlation on")

        funnel_persons_query = self.get_funnel_actors_cte()
        target_step = self.context.max_steps
        exclude_property_names = self.query.funnelCorrelationExcludeNames or []

        person_prop_query = self._get_properties_prop_clause()
        aggregation_join_query = self._get_aggregation_join_query()

        query = parse_select(
            f"""
            WITH
                funnel_actors AS (
                    {{funnel_persons_query}}
                ),
                {target_step} AS target_step
            SELECT
                concat(prop.1, '::', prop.2) as name,
                -- We generate a unique identifier for each property value as: PropertyName::Value
                countDistinctIf(actor_id, steps = target_step) AS success_count,
                countDistinctIf(actor_id, steps <> target_step) AS failure_count
            FROM (
                SELECT
                    actor_id,
                    funnel_actors.steps as steps,
                    /*
                        We can extract multiple property values at the same time, since we're
                        already querying the person table.
                        This gives us something like:
                        --------------------
                        person1, steps, [property_value_0, property_value_1, property_value_2]
                        person2, steps, [property_value_0, property_value_1, property_value_2]

                        To group by property name, we need to extract the property from the array. ArrayJoin helps us do that.
                        It transforms the above into:

                        --------------------

                        person1, steps, property_value_0
                        person1, steps, property_value_1
                        person1, steps, property_value_2

                        person2, steps, property_value_0
                        person2, steps, property_value_1
                        person2, steps, property_value_2

                        To avoid clashes and clarify the values, we also zip with the property name, to generate
                        tuples like: (property_name, property_value), which we then group by
                    */
                    {person_prop_query}
                FROM funnel_actors
                {aggregation_join_query}

            ) aggregation_target_with_props
            -- Group by the tuple items: (property_name, property_value) generated by zip
            GROUP BY prop.1, prop.2
            HAVING prop.1 NOT IN {exclude_property_names}

            UNION ALL

            -- :HACKY: HogQL does not have access to a CTE in the second union query, thus
            -- we're repeating the CTE here. This likely is a big hit on query performance.
            WITH
                funnel_actors AS (
                    {{funnel_persons_query}}
                ),
                {target_step} AS target_step

            SELECT
                '{self.TOTAL_IDENTIFIER}' as name,
                countDistinctIf(actor_id, steps = target_step) AS success_count,
                countDistinctIf(actor_id, steps <> target_step) AS failure_count
            FROM funnel_actors
        """,
            placeholders={
                "funnel_persons_query": funnel_persons_query,
            },
        )

        return query

    def get_funnel_actors_cte(self) -> ast.SelectQuery:
        extra_fields = ["steps", "final_timestamp", "first_timestamp"]

        for prop in self.properties_to_include:
            extra_fields.append(prop)

        return self._funnel_actors_generator.actor_query(extra_fields=extra_fields)

    def _get_events_join_query(self) -> str:
        """
        This query is used to join and filter the events table corresponding to the funnel_actors CTE.
        It expects the following variables to be present in the CTE expression:
            - funnel_actors
            - date_to
            - date_from
            - funnel_step_names
        """
        windowInterval = self.context.funnelWindowInterval
        windowIntervalUnit = funnel_window_interval_unit_to_sql(self.context.funnelWindowIntervalUnit)

        return f"""
            {self._get_aggregation_target_join_query()}

            -- Make sure we're only looking at events before the final step, or
            -- failing that, date_to
            WHERE
                -- add this condition in to ensure we can filter events before
                -- joining funnel_actors
                toTimeZone(toDateTime(event.timestamp), 'UTC') >= date_from
                AND toTimeZone(toDateTime(event.timestamp), 'UTC') < date_to

                AND event.team_id = {self.context.team.pk}

                -- Add in per actor filtering on event time range. We just want
                -- to include events that happened within the bounds of the
                -- actors time in the funnel.
                AND toTimeZone(toDateTime(event.timestamp), 'UTC') > funnel_actors.first_timestamp
                AND toTimeZone(toDateTime(event.timestamp), 'UTC') < coalesce(
                    funnel_actors.final_timestamp,
                    toTimeZone(funnel_actors.first_timestamp, 'UTC') + INTERVAL {windowInterval} {windowIntervalUnit},
                    date_to)
                    -- Ensure that the event is not outside the bounds of the funnel conversion window

                -- Exclude funnel steps
                AND event.event NOT IN funnel_step_names
        """

    def _get_aggregation_target_join_query(self) -> str:
        aggregation_person_join = f"""
            JOIN funnel_actors
                ON event.person_id = funnel_actors.actor_id
        """

        aggregation_group_join = f"""
            JOIN funnel_actors
                ON funnel_actors.actor_id = event.$group_{self.funnels_query.aggregation_group_type_index}
            """

        return (
            aggregation_group_join
            if self.funnels_query.aggregation_group_type_index is not None
            else aggregation_person_join
        )

    def _get_aggregation_join_query(self):
        if self.funnels_query.aggregation_group_type_index is None:
            return f"JOIN (SELECT id, properties as person_props FROM persons) persons ON persons.id = funnel_actors.actor_id"
        else:
            group_type_index = self.funnels_query.aggregation_group_type_index
            return f"""
                LEFT JOIN (
                    SELECT
                        key,
                        properties --AS group_properties_{group_type_index}
                    FROM groups
                    WHERE index = {group_type_index}
                ) groups_{group_type_index}
                ON funnel_actors.actor_id == groups_{group_type_index}.key
            """

    def _get_properties_prop_clause(self):
        assert self.query.funnelCorrelationNames is not None

        if self.funnels_query.aggregation_group_type_index is None:
            properties_prefix = "person_props"
        else:
            properties_prefix = f"groups_{self.funnels_query.aggregation_group_type_index}.properties"
        if "$all" in self.query.funnelCorrelationNames:
            return f"arrayJoin(JSONExtractKeysAndValues({properties_prefix}, 'String')) as prop"
        else:
            props = [
                f"JSONExtractString({properties_prefix}, '{property_name}')"
                for property_name in self.query.funnelCorrelationNames
            ]
            props_str = ", ".join(props)
            return f"arrayJoin(arrayZip({self.query.funnelCorrelationNames}, [{props_str}])) as prop"

    def _get_funnel_step_names(self) -> list[str]:
        events: set[str] = set()
        for entity in self.funnels_query.series:
            if isinstance(entity, ActionsNode):
                action = Action.objects.get(pk=int(entity.id), team__project_id=self.context.team.project_id)
                events.update([x for x in action.get_step_events() if x])
            elif isinstance(entity, EventsNode):
                if entity.event is not None:
                    events.add(entity.event)
            else:
                raise ValidationError("Data warehouse nodes are not supported here")

        return sorted(events)

    @property
    def properties_to_include(self) -> list[str]:
        props_to_include: list[str] = []
        # TODO: implement or remove
        # if self.query.funnelCorrelationType == FunnelCorrelationResultsType.PROPERTIES:
        #     assert self.query.funnelCorrelationNames is not None

        #     # When dealing with properties, make sure funnel response comes with properties
        #     # so we don't have to join on persons/groups to get these properties again

        #     for property_name in self.query.funnelCorrelationNames:
        #         if self.funnels_query.aggregation_group_type_index is not None:
        #             if "$all" == property_name:
        #                 return []
        #         else:
        #             if "$all" == property_name:
        #                 return []

        return props_to_include

    def support_autocapture_elements(self) -> bool:
        if (
            self.query.funnelCorrelationType == FunnelCorrelationResultsType.EVENT_WITH_PROPERTIES
            and AUTOCAPTURE_EVENT in (self.query.funnelCorrelationEventNames or [])
        ):
            return True
        return False

    @staticmethod
    def are_results_insignificant(event_contingency_table: EventContingencyTable) -> bool:
        """
        Check if the results are insignificant, i.e. if the success/failure counts are
        significantly different from the total counts
        """

        total_count = event_contingency_table.success_total + event_contingency_table.failure_total

        if event_contingency_table.visited.success_count + event_contingency_table.visited.failure_count < min(
            FunnelCorrelationQueryRunner.MIN_PERSON_COUNT,
            FunnelCorrelationQueryRunner.MIN_PERSON_PERCENTAGE * total_count,
        ):
            return True

        return False


def get_entity_odds_ratio(event_contingency_table: EventContingencyTable, prior_counts: int) -> EventOddsRatio:
    # Add 1 to all values to prevent divide by zero errors, and introduce a [prior](https://en.wikipedia.org/wiki/Prior_probability)
    odds_ratio = (
        (event_contingency_table.visited.success_count + prior_counts)
        * (event_contingency_table.failure_total - event_contingency_table.visited.failure_count + prior_counts)
    ) / (
        (event_contingency_table.success_total - event_contingency_table.visited.success_count + prior_counts)
        * (event_contingency_table.visited.failure_count + prior_counts)
    )

    return EventOddsRatio(
        event=event_contingency_table.event,
        success_count=event_contingency_table.visited.success_count,
        failure_count=event_contingency_table.visited.failure_count,
        odds_ratio=odds_ratio,
        correlation_type="success" if odds_ratio > 1 else "failure",
    )
