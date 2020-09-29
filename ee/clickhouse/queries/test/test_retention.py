from typing import Any, Dict, List

from posthog.models.filter import Filter
from posthog.models.team import Team
from posthog.queries.base import BaseQuery


class ClickhouseTrends(BaseQuery):
    def run(self, filter: Filter, team: Team, *args, **kwargs) -> List[Dict[str, Any]]:
        return []
