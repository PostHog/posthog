from typing import Dict, Tuple

from ee.clickhouse.queries.paths.paths_event_query import ClickhousePathEventQuery
from posthog.constants import FUNNEL_PATH_BETWEEN_STEPS
from posthog.models import Filter
from posthog.queries.funnels.funnel_persons import ClickhouseFunnelActors
from posthog.queries.paths.paths import Paths


class ClickhousePaths(Paths):
    event_query = ClickhousePathEventQuery

    def get_edge_weight_clause(self) -> Tuple[str, Dict]:
        params: Dict[str, int] = {}

        conditions = []

        if self._filter.min_edge_weight:
            params["min_edge_weight"] = self._filter.min_edge_weight
            conditions.append("event_count >= %(min_edge_weight)s")

        if self._filter.max_edge_weight:
            params["max_edge_weight"] = self._filter.max_edge_weight
            conditions.append("event_count <= %(max_edge_weight)s")

        if conditions:
            return f"HAVING {' AND '.join(conditions)}", params

        return "", params

    def get_target_point_filter(self) -> str:
        if self._filter.end_point and self._filter.start_point:
            return "WHERE start_target_index > 0 AND end_target_index > 0"
        elif self._filter.end_point or self._filter.start_point:
            return f"WHERE target_index > 0"
        else:
            return ""

    def get_path_query_funnel_cte(self, funnel_filter: Filter):
        funnel_persons_generator = ClickhouseFunnelActors(
            funnel_filter,
            self._team,
            include_timestamp=bool(self._filter.funnel_paths),
            include_preceding_timestamp=self._filter.funnel_paths == FUNNEL_PATH_BETWEEN_STEPS,
        )
        funnel_persons_query, funnel_persons_param = funnel_persons_generator.actor_query(limit_actors=False)
        funnel_persons_query_new_params = funnel_persons_query.replace("%(", "%(funnel_")
        new_funnel_params = {"funnel_" + str(key): val for key, val in funnel_persons_param.items()}
        self.params.update(new_funnel_params)
        return f"""
        WITH {self.event_query.FUNNEL_PERSONS_ALIAS} AS (
            {funnel_persons_query_new_params}
        )
        """

    def should_query_funnel(self) -> bool:
        if self._filter.funnel_paths and self._funnel_filter:
            return True
        return False
