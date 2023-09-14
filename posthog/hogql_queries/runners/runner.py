import inspect
import json
from typing import Any, Dict, Optional

from posthog.models.team.team import Team
from posthog.types import InsightQueryNode
from posthog.utils import generate_cache_key


class QueryRunner:
    def __init__(self, query: InsightQueryNode, team: Team) -> None:
        self.query = query
        self.team = team

    def to_dict(self) -> Dict[str, Any]:
        ret = {}

        for _, func in inspect.getmembers(self, inspect.ismethod):
            if hasattr(func, "include_dict"):  # provided by @include_dict decorator
                ret.update(func())

        return ret

    def toJSON(self):
        return json.dumps(self.to_dict(), default=lambda o: o.__dict__, sort_keys=True, indent=4)

    def cache_key(self, cache_invalidation_key: Optional[str] = None):
        payload = f"query_{self.query.kind}_{self.toJSON()}_{self.team.pk}"
        if cache_invalidation_key:
            payload += f"_{cache_invalidation_key}"

        return generate_cache_key(payload)

    def query_tags(self) -> Dict[str, Any]:
        ret = {}

        for _, func in inspect.getmembers(self, inspect.ismethod):
            if hasattr(func, "include_query_tags"):  # provided by @include_query_tags decorator
                ret.update(func())

        return ret
