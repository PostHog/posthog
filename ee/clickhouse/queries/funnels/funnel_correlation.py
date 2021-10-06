import dataclasses
from typing import Any, Dict, List, Literal, Tuple, TypedDict

from ee.clickhouse.client import sync_execute
from ee.clickhouse.queries.funnels.funnel_persons import ClickhouseFunnelPersons
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
    def __init__(self, filter: Filter, team: Team) -> None:
        self._filter = filter
        self._team = team

        if self._filter.funnel_step is None:
            self._filter = self._filter.with_data({"funnel_step": 1})
            # Funnel Step by default set to 1, to give us all people who entered the funnel

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
        6.
        
        And the odds that a person signs up given they didn't watch the video is
        2 / 12.

        So we say the odds ratio is 5 / 6 over 2 / 12 = 5 . The further away the
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
        event_contingency_tables = self.get_partial_event_contingency_tables()

        odds_ratios = [get_entity_odds_ratio(event_stats) for event_stats in event_contingency_tables]

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
        return {"events": positively_correlated_events[:10] + negatively_correlated_events[:10]}

    def get_partial_event_contingency_tables(self) -> List[EventContingencyTable]:
        """
        For each event a person that started going through the funnel, gets stats
        for how many of these users are sucessful and how many are unsuccessful.

        It's a partial table as it doesn't include numbers of the negation of the
        event, but does include the total success/failure numbers, which is enough
        for us to calculate the odds ratio.
        """
        funnel_persons_query, funnel_persons_params = self.get_funnel_persons_cte()

        # TODO: replace countIf with the distinct equivalent
        query = f"""
            WITH 
                funnel_people AS ({funnel_persons_query}),
                toDateTime(%(date_to)s) AS date_to,
                %(target_step)s AS target_step
            SELECT 
                event.event AS name, 

                -- If we have a timestamp, we know the person reached the end of the
                -- funnel (I think)
                countIf(person.steps = target_step) AS success_count,

                -- And the converse being for failures
                countIf(person.steps <> target_step) AS failure_count
            FROM events AS event
            
            JOIN person_distinct_id AS pdi
                ON pdi.distinct_id = events.distinct_id

            -- Right join, so we can get the total success/failure numbers as well
            RIGHT JOIN funnel_people AS person
                ON pdi.person_id = person.person_id

            -- Make sure we're only looking at events before the final step, or
            -- failing that, date_to
            -- TODO: add a lower bounds for events
            WHERE event.timestamp < COALESCE(person.final_timestamp, date_to)
            AND event.timestamp >= person.timestamp
            GROUP BY name
            WITH TOTALS
        """
        params = {
            **funnel_persons_params,
            "date_to": self._filter.date_to,
            "target_step": len(self._filter.entities),
        }
        results_then_total = sync_execute(query, params)

        # Make typechecking happy. It should never be anything other than a list
        assert isinstance(results_then_total, list)

        # The last entry will give us the total funnel failures and successes
        results, (_, success_total, failure_total) = results_then_total[:-1], results_then_total[-1]

        # Add a little structure, and keep it close to the query definition so it's
        # obvious what's going on with result indices.
        return [
            EventContingencyTable(
                event=result[0],
                visited=EventStats(success_count=result[1], failure_count=result[2]),
                success_total=success_total,
                failure_total=failure_total,
            )
            for result in results
        ]

    def get_funnel_persons_cte(self) -> Tuple[str, Dict[str, Any]]:
        funnel_persons_generator = ClickhouseFunnelPersons(
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

        return (
            funnel_persons_generator.get_query(extra_fields=["steps", "final_timestamp"]),
            funnel_persons_generator.params,
        )


def get_entity_odds_ratio(event_contingency_table: EventContingencyTable) -> EventOddsRatio:
    if event_contingency_table.success_total and event_contingency_table.failure_total:
        odds_ratio = (event_contingency_table.visited.success_count / event_contingency_table.success_total) / (
            event_contingency_table.visited.failure_count / event_contingency_table.failure_total
        )
    else:
        odds_ratio = 1

    return EventOddsRatio(
        event=event_contingency_table.event,
        success_count=event_contingency_table.visited.success_count,
        failure_count=event_contingency_table.visited.failure_count,
        odds_ratio=odds_ratio,
        correlation_type="success" if odds_ratio > 1 else "failure",
    )
