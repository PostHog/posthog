from typing import Dict, List, Optional, Tuple

from posthog.models.filters.sessions_filter import SessionsFilter
from posthog.models.team import Team

SESSIONS_LIST_DEFAULT_LIMIT = 50


class RunUntilResultsMixin:
    "Sessions queries do post-filtering based on session recordings. This makes sure we return some data every page"

    def run(self, filter: SessionsFilter, team: Team, *args, **kwargs) -> Tuple[List[Dict], Optional[Dict]]:
        limit = kwargs.get("limit", SESSIONS_LIST_DEFAULT_LIMIT)

        results = []

        while True:
            page, pagination = self.run_batch(filter, team, *args, **kwargs)
            results.extend(page)

            if len(results) >= limit or pagination is None:
                return results, pagination
            filter = filter.with_data({"pagination": pagination})
