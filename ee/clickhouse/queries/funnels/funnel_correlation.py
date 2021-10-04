from typing import List, TypedDict

from posthog.models import Filter, Team
from posthog.models.filters import Filter


class EventOddsRatio(TypedDict):
    event: str
    success_count: int
    failure_count: int
    odds_ratio: float


class FunnelCorrelationResponse(TypedDict):
    """
    The structure that the diagnose response will be returned in.
    NOTE: TypedDict is used here to comply with existing formats from other
    queries, but we could use, for example, a dataclass
    """

    events: List[EventOddsRatio]


class FunnelCorrelation:
    def __init__(self, filter: Filter, team: Team) -> None:
        self._filter = filter
        self._team = team

    def run(self, *args, **kwargs) -> FunnelCorrelationResponse:
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
         - there may be a large but not hug number of distinct events, let's say
           100 different names for events. We should avoid n+1 queries for the
           event names dimension

        Contincency tables are something we can pull out of the db, so we can
        have a query that:

         1. filters people by the cohort criteria
         2. groups these people by the success criteria
         3. groups people by our criterion with which we want to test
            correlation, e.g. "watched video"

        """
        num_people_by_success_by_event_visited = get_people_by_success_by_event_visited(
            team_id=self._team.pk, filter=self._filter
        )

        odds_ratios = [get_entity_odds_ratio(event_stats) for event_stats in num_people_by_success_by_event_visited]

        # Return the top ten positively correlated events
        return {"events": sorted(odds_ratios, key=lambda odds_ratio: -odds_ratio["odds_ratio"])[:10]}


class EventStats(TypedDict):
    success_count: int
    failure_count: int


class EventContingencyTable(TypedDict):
    """
    Represents a contingency table for a single event.
    """

    event: str

    visited: EventStats
    not_visited: EventStats


def get_people_by_success_by_event_visited(team_id: int, filter: Filter):
    return [
        EventContingencyTable(
            event="signup",
            visited=EventStats(success_count=1, failure_count=2),
            not_visited=EventStats(success_count=3, failure_count=4),
        ),
        EventContingencyTable(
            event="watch video",
            visited=EventStats(success_count=1, failure_count=2),
            not_visited=EventStats(success_count=3, failure_count=4),
        ),
    ]


def get_entity_odds_ratio(event_contingency_table: EventContingencyTable) -> EventOddsRatio:
    return EventOddsRatio(
        event=event_contingency_table["event"],
        success_count=event_contingency_table["visited"]["success_count"],
        failure_count=event_contingency_table["visited"]["failure_count"],
        odds_ratio=(
            (
                event_contingency_table["visited"]["success_count"]
                / (
                    event_contingency_table["visited"]["success_count"]
                    + event_contingency_table["visited"]["failure_count"]
                )
            )
            / (
                event_contingency_table["not_visited"]["success_count"]
                / (
                    event_contingency_table["not_visited"]["success_count"]
                    + event_contingency_table["not_visited"]["failure_count"]
                )
            )
        ),
    )
