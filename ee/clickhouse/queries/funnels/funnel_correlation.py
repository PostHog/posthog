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
        pass

    def run(self, *args, **kwargs) -> FunnelCorrelationResponse:
        # TODO: add implementation
        # Top 10 success
        # Bottom 10 failures
        return {
            "events": [
                # Top 10
                {"event": "Event A", "success_count": 1, "failure_count": 4, "odds_ratio": 10},
                {"event": "Event B", "success_count": 1, "failure_count": 4, "odds_ratio": 9.4},
                {"event": "Event C", "success_count": 1, "failure_count": 4, "odds_ratio": 5.4},
                {"event": "Event D", "success_count": 1, "failure_count": 4, "odds_ratio": 3.4},
                {"event": "Event E", "success_count": 1, "failure_count": 4, "odds_ratio": 2.6},
                {"event": "Event F", "success_count": 1, "failure_count": 4, "odds_ratio": 2.5},
                {"event": "Event G", "success_count": 1, "failure_count": 4, "odds_ratio": 2.1},
                {"event": "Event H", "success_count": 1, "failure_count": 4, "odds_ratio": 2.0},
                {"event": "Event I", "success_count": 1, "failure_count": 4, "odds_ratio": 1.5},
                {"event": "Event J", "success_count": 1, "failure_count": 4, "odds_ratio": 1.2},
            ]
        }
