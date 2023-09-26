from abc import ABC, abstractmethod
from typing import Any, Optional, Dict

from posthog.hogql.timings import HogQLTimings
from posthog.models import Team
from posthog.schema import HogQLQueryResponse
from posthog.types import WebAnalyticsQueryNode
from posthog.utils import generate_cache_key


class WebAnalyticsQueryRunner(ABC):
    team: Team
    timings: HogQLTimings
    query: WebAnalyticsQueryNode

    def __init__(
        self, query: WebAnalyticsQueryNode | Dict[str, Any], team: Team, timings: Optional[HogQLTimings] = None
    ):
        self.team = team
        self.timings = timings or HogQLTimings()
        if isinstance(query, WebAnalyticsQueryNode):
            self.query = query
        else:
            self.query = WebAnalyticsQueryNode.model_validate(query)

    @abstractmethod
    def calculate(self) -> HogQLQueryResponse:
        raise NotImplementedError()

    def run(self) -> HogQLQueryResponse:
        return self.calculate()

    def toJSON(self) -> str:
        return self.query.model_dump_json(exclude_defaults=True, exclude_none=True)

    def _cache_key(self) -> str:
        return generate_cache_key(
            f"query_{self.__class__.__name__}_{self.toJSON()}_{self.team.pk}_{self.team.timezone}"
        )

    @abstractmethod
    def _is_stale(self, cached_result_package):
        raise NotImplementedError()

    @abstractmethod
    def _refresh_frequency(self):
        raise NotImplementedError()
