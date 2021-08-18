from abc import ABC
from typing import List, Tuple

from ee.clickhouse.client import sync_execute
from ee.clickhouse.queries.paths.path_event_query import PathEventQuery
from ee.clickhouse.sql.paths.path import PATH_ARRAY_QUERY
from posthog.constants import FUNNEL_WINDOW_INTERVAL, FUNNEL_WINDOW_INTERVAL_UNIT, LIMIT
from posthog.models import Filter, Team
from posthog.models.filters.path_filter import PathFilter
from posthog.queries.funnel import Funnel

EVENT_IN_SESSION_LIMIT_DEFAULT = 5
SESSION_TIME_THRESHOLD_DEFAULT = 1800000  # milliseconds to 30 minutes


class ClickhousePathBase(ABC, Funnel):
    _filter: PathFilter
    _team: Team

    def __init__(self, filter: PathFilter, team: Team) -> None:
        self._filter = filter
        self._team = team
        self.params = {
            "team_id": self._team.pk,
            "events": [],  # purely a speed optimization, don't need this for filtering
            "event_in_session_limit": EVENT_IN_SESSION_LIMIT_DEFAULT,
            "session_time_threshold": SESSION_TIME_THRESHOLD_DEFAULT,
            "autocapture_match": "%autocapture:%",
        }

    def run(self, *args, **kwargs):

        results = self._exec_query()
        return self._format_results(results)

    def _format_results(self, results):
        if not results or len(results) == 0:
            return []

        resp = []
        for res in results:
            resp.append(
                {"source": res[0], "target": res[1], "value": res[2],}
            )
        return resp

    def _exec_query(self) -> List[Tuple]:
        query = self.get_query()
        return sync_execute(query, self.params)

    def get_query(self) -> str:
        path_event_query, params = PathEventQuery(filter=self._filter, team_id=self._team.pk).get_query()
        self.params.update(params)
        return PATH_ARRAY_QUERY.format(path_event_query=path_event_query, boundary_event_filter="")
