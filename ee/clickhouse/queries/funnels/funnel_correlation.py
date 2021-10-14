import dataclasses
from os import stat
from typing import Any, Dict, List, Literal, Tuple, TypedDict, cast

from rest_framework.exceptions import ValidationError

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.property import get_property_string_expr
from ee.clickhouse.queries.column_optimizer import ColumnOptimizer
from ee.clickhouse.queries.funnels.funnel_persons import ClickhouseFunnelPersons
from ee.clickhouse.queries.person_query import ClickhousePersonQuery
from ee.clickhouse.sql.person import GET_TEAM_PERSON_DISTINCT_IDS
from posthog.constants import FunnelCorrelationType
from posthog.models import Filter, Team
from posthog.models.filters import Filter


class EventOddsRatio(TypedDict):
    event: str

    success_count: int
    failure_count: int

    odds_ratio: float
    correlation_type: Literal["success", "failure"]


class FunnelCorrelationResponse(TypedDict):
    """
    The structure that the diagnose response will be returned in.
    NOTE: TypedDict is used here to comply with existing formats from other
    queries, but we could use, for example, a dataclass
    """

    events: List[EventOddsRatio]
    skewed: bool


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


class FunnelCorrelation:

    TOTAL_IDENTIFIER = "Total_Values_In_Query"
    MIN_PERSON_COUNT = 25
    MIN_PERSON_PERCENTAGE = 0.02
    PRIOR_COUNT = 1

    def __init__(self, filter: Filter, team: Team) -> None:
        self._filter = filter
        self._team = team

        if self._filter.funnel_step is None:
            self._filter = self._filter.with_data({"funnel_step": 1})
            # Funnel Step by default set to 1, to give us all people who entered the funnel

        # Used for generating the funnel persons cte
        self._funnel_persons_generator = ClickhouseFunnelPersons(
            self._filter,
            self._team,
            # NOTE: we want to include the latest timestamp of the `target_step`,
            # from this we can deduce if the person reached the end of the funnel,
            # i.e. successful
            include_timestamp=True,
            # NOTE: we don't need these as we have all the information we need to
            # deduce if the person was successful or not
            include_preceding_timestamp=False,
            no_person_limit=True,
        )

    def get_contingency_table_query(self) -> Tuple[str, Dict[str, Any]]:
        """
        Returns a query string and params, which are used to generate the contingency table.
        The query returns success and failure count for event / property values, along with total success and failure counts.
        """
        if self._filter.correlation_type == FunnelCorrelationType.PROPERTIES:
            return self.get_properties_query()

        return self.get_event_query()

    def get_event_query(self) -> Tuple[str, Dict[str, Any]]:

        funnel_persons_query, funnel_persons_params = self.get_funnel_persons_cte()

        query = f"""
            WITH
                funnel_people as ({funnel_persons_query}),
                toDateTime(%(date_to)s) AS date_to,
                toDateTime(%(date_from)s) AS date_from,
                %(target_step)s AS target_step,
                %(funnel_step_names)s as funnel_step_names

            SELECT
                event.event AS name,

                -- If we have a `person.steps = target_step`, we know the person
                -- reached the end of the funnel
                countDistinctIf(
                    person.person_id,
                    person.steps = target_step
                ) AS success_count,

                -- And the converse being for failures
                countDistinctIf(
                    person.person_id,
                    person.steps <> target_step
                ) AS failure_count

            FROM events AS event

            JOIN ({GET_TEAM_PERSON_DISTINCT_IDS}) AS pdi
                ON pdi.distinct_id = events.distinct_id

            -- NOTE: I would love to right join here, so we count get total
            -- success/failure numbers in one pass, but this causes out of memory
            -- error mentioning issues with right filling. I'm sure there's a way
            -- to do it but lifes too short.
            JOIN funnel_people AS person
                ON pdi.person_id = person.person_id

            -- Make sure we're only looking at events before the final step, or
            -- failing that, date_to
            WHERE
                -- add this condition in to ensure we can filter events before
                -- joining funnel_people
                event.timestamp >= date_from
                AND event.timestamp < date_to

                AND event.team_id = {self._team.pk}

                -- Add in per person filtering on event time range. We just want
                -- to include events that happened within the bounds of the
                -- persons time in the funnel.
                AND event.timestamp > person.first_timestamp
                AND event.timestamp < COALESCE(
                    person.final_timestamp,
                    person.first_timestamp + INTERVAL {self._funnel_persons_generator._filter.funnel_window_interval} {self._funnel_persons_generator._filter.funnel_window_interval_unit_ch()},
                    date_to)
                    -- Ensure that the event is not outside the bounds of the funnel conversion window

                -- Exclude funnel steps
                AND event.event NOT IN funnel_step_names
            GROUP BY name

            -- To get the total success/failure numbers, we do an aggregation on
            -- the funnel people CTE and count distinct person_ids
            UNION ALL

            SELECT
                -- Use null as a special marker for the WITH TOTALS equivelant.
                -- We're not using WITH TOTALS because the resulting queries are
                -- not runnable in Metabase
                '{self.TOTAL_IDENTIFIER}' as name,

                countDistinctIf(
                    person.person_id,
                    person.steps = target_step
                ) AS success_count,

                countDistinctIf(
                    person.person_id,
                    person.steps <> target_step
                ) AS failure_count
            FROM funnel_people AS person
        """
        params = {
            **funnel_persons_params,
            "funnel_step_names": [entity.id for entity in self._filter.events],
            "target_step": len(self._filter.entities),
        }

        return query, params

    def get_properties_query(self) -> Tuple[str, Dict[str, Any]]:

        if not self._filter.correlation_property_names:
            raise ValidationError("Property Correlation expects atleast one Property to run correlation on")

        funnel_persons_query, funnel_persons_params = self.get_funnel_persons_cte()

        person_prop_query, person_prop_params = self._get_properties_prop_clause()

        person_query, person_query_params = ClickhousePersonQuery(
            self._filter, self._team.pk, ColumnOptimizer(self._filter, self._team.pk)
        ).get_query()

        query = f"""
            WITH
                funnel_people as ({funnel_persons_query}),
                %(target_step)s AS target_step
            SELECT
                concat(prop.1, '::', prop.2) as name,
                -- We generate a unique identifier for each property value as: PropertyName::Value
                countDistinctIf(person_id, steps = target_step) AS success_count,
                countDistinctIf(person_id, steps <> target_step) AS failure_count
            FROM (
                SELECT
                    person_id,
                    funnel_people.steps as steps,
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
                FROM funnel_people
                JOIN ({person_query}) person
                ON person.id = funnel_people.person_id
            ) person_with_props
            -- Group by the tuple items: (property_name, property_value) generated by zip
            GROUP BY prop.1, prop.2
            UNION ALL
            SELECT
                '{self.TOTAL_IDENTIFIER}' as name,
                countDistinctIf(person_id, steps = target_step) AS success_count,
                countDistinctIf(person_id, steps <> target_step) AS failure_count
            FROM funnel_people
        """
        params = {
            **funnel_persons_params,
            **person_prop_params,
            **person_query_params,
            "target_step": len(self._filter.entities),
            "property_names": self._filter.correlation_property_names,
        }

        return query, params

    def _get_properties_prop_clause(self):

        if "$all" in cast(list, self._filter.correlation_property_names):
            return (
                f"""
            arrayMap(x -> x.1, JSONExtractKeysAndValuesRaw({ClickhousePersonQuery.PERSON_PROPERTIES_ALIAS})) as person_prop_keys,
            arrayJoin(
                arrayZip(
                    person_prop_keys,
                    arrayMap(x -> trim(BOTH '"' FROM JSONExtractRaw({ClickhousePersonQuery.PERSON_PROPERTIES_ALIAS}, x)), person_prop_keys)
                )
            ) as prop
            """,
                {},
            )
        else:
            person_property_expressions = []
            person_property_params = {}
            for index, property_name in enumerate(cast(list, self._filter.correlation_property_names)):
                param_name = f"property_name_{index}"
                expression, _ = get_property_string_expr(
                    "person", property_name, f"%({param_name})s", ClickhousePersonQuery.PERSON_PROPERTIES_ALIAS,
                )
                person_property_params[param_name] = property_name
                person_property_expressions.append(expression)

            return (
                f"""
                arrayJoin(arrayZip(
                        %(property_names)s,
                        [{','.join(person_property_expressions)}]
                    )) as prop
            """,
                person_property_params,
            )

    def run(self) -> FunnelCorrelationResponse:
        """
        Run the diagnose query.

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

        """

        event_contingency_tables, success_total, failure_total = self.get_partial_event_contingency_tables()

        if not success_total or not failure_total:
            return {"events": [], "skewed": True}

        skewed_totals = False

        # If the ratio is greater than 1:10, then we have a skewed result, so we should
        # warn the user.
        if success_total / failure_total > 10 or failure_total / success_total > 10:
            skewed_totals = True

        odds_ratios = [
            get_entity_odds_ratio(event_stats, FunnelCorrelation.PRIOR_COUNT)
            for event_stats in event_contingency_tables
            if not FunnelCorrelation.are_results_insignificant(event_stats)
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
        return {
            "events": positively_correlated_events[:10] + negatively_correlated_events[:10],
            "skewed": skewed_totals,
        }

    def get_partial_event_contingency_tables(self) -> Tuple[List[EventContingencyTable], int, int]:
        """
        For each event a person that started going through the funnel, gets stats
        for how many of these users are sucessful and how many are unsuccessful.

        It's a partial table as it doesn't include numbers of the negation of the
        event, but does include the total success/failure numbers, which is enough
        for us to calculate the odds ratio.
        """

        query, params = self.get_contingency_table_query()
        results_with_total = sync_execute(query, params)

        # Get the total success/failure counts from the results
        results = [result for result in results_with_total if result[0] != self.TOTAL_IDENTIFIER]
        _, success_total, failure_total = [
            result for result in results_with_total if result[0] == self.TOTAL_IDENTIFIER
        ][0]

        # Add a little structure, and keep it close to the query definition so it's
        # obvious what's going on with result indices.
        return (
            [
                EventContingencyTable(
                    event=result[0],
                    visited=EventStats(success_count=result[1], failure_count=result[2]),
                    success_total=success_total,
                    failure_total=failure_total,
                )
                for result in results
            ],
            success_total,
            failure_total,
        )

    def get_funnel_persons_cte(self) -> Tuple[str, Dict[str, Any]]:

        return (
            self._funnel_persons_generator.get_query(extra_fields=["steps", "final_timestamp", "first_timestamp"]),
            self._funnel_persons_generator.params,
        )

    @staticmethod
    def are_results_insignificant(event_contingency_table: EventContingencyTable) -> bool:
        """
        Check if the results are insignificant, i.e. if the success/failure counts are
        significantly different from the total counts
        """

        total_count = event_contingency_table.success_total + event_contingency_table.failure_total

        if event_contingency_table.visited.success_count + event_contingency_table.visited.failure_count < min(
            FunnelCorrelation.MIN_PERSON_COUNT, FunnelCorrelation.MIN_PERSON_PERCENTAGE * total_count
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
