from typing import List, TypedDict

from posthog.models import Team
from posthog.models.filters.diagnose_filter import DiagnoseFilter


class EventOddsRatio(TypedDict):
    event: str
    value: float


class DiagnoseResponse(TypedDict):
    """
    The structure that the diagnose response will be returned in.

    NOTE: TypedDict is used here to comply with existing formats from other
    queries, but we could use, for example, a dataclass
    """

    events: List[EventOddsRatio]


class Diagnose:
    def __init__(self, *args, **kwargs) -> None:
        super().__init__()

    def run(self, filter: DiagnoseFilter, team: Team, *args, **kwargs) -> DiagnoseResponse:
        raise NotImplementedError("Diagnose Query not implemented for postgres")
