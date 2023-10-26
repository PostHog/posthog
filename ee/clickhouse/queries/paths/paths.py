from re import escape
from typing import Dict, Literal, Optional, Tuple, Union, cast

from jsonschema import ValidationError

from ee.clickhouse.queries.paths.paths_event_query import ClickhousePathEventQuery
from posthog.constants import FUNNEL_PATH_BETWEEN_STEPS
from posthog.models import Filter
from posthog.models.filters.path_filter import PathFilter
from posthog.models.team.team import Team
from posthog.queries.funnels.funnel_persons import ClickhouseFunnelActors
from posthog.queries.paths.paths import Paths


class ClickhousePaths(Paths):
    event_query = ClickhousePathEventQuery

    def __init__(self, filter: PathFilter, team: Team, funnel_filter: Optional[Filter] = None) -> None:
        super().__init__(filter, team, funnel_filter)

        if self._filter.path_groupings:
            regex_groupings = []
            for grouping in self._filter.path_groupings:
                regex_grouping = escape(grouping)
                # don't allow arbitrary regex for now
                regex_grouping = regex_grouping.replace("\\*", ".*")
                regex_groupings.append(regex_grouping)
            self.params["regex_groupings"] = regex_groupings

        if (
            self._filter.max_edge_weight
            and self._filter.min_edge_weight
            and self._filter.max_edge_weight < self._filter.min_edge_weight
        ):
            raise ValidationError("Max Edge weight can't be lower than min edge weight")

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

    def get_target_clause(self) -> Tuple[str, Dict]:
        params: Dict[str, Union[str, None]] = {
            "target_point": None,
            "secondary_target_point": None,
        }

        if self._filter.end_point and self._filter.start_point:
            params.update(
                {
                    "target_point": self._filter.end_point,
                    "secondary_target_point": self._filter.start_point,
                }
            )

            clause = f"""
            , indexOf(compact_path, %(secondary_target_point)s) as start_target_index
            , if(start_target_index > 0, arraySlice(compact_path, start_target_index), compact_path) as start_filtered_path
            , if(start_target_index > 0, arraySlice(timings, start_target_index), timings) as start_filtered_timings
            , indexOf(start_filtered_path, %(target_point)s) as end_target_index
            , if(end_target_index > 0, arrayResize(start_filtered_path, end_target_index), start_filtered_path) as filtered_path
            , if(end_target_index > 0, arrayResize(start_filtered_timings, end_target_index), start_filtered_timings) as filtered_timings
            , if(length(filtered_path) > %(event_in_session_limit)s, arrayConcat(arraySlice(filtered_path, 1, intDiv(%(event_in_session_limit)s,2)), ['...'], arraySlice(filtered_path, (-1)*intDiv(%(event_in_session_limit)s, 2), intDiv(%(event_in_session_limit)s, 2))), filtered_path) AS limited_path
            , if(length(filtered_timings) > %(event_in_session_limit)s, arrayConcat(arraySlice(filtered_timings, 1, intDiv(%(event_in_session_limit)s, 2)), [filtered_timings[1+intDiv(%(event_in_session_limit)s, 2)]], arraySlice(filtered_timings, (-1)*intDiv(%(event_in_session_limit)s, 2), intDiv(%(event_in_session_limit)s, 2))), filtered_timings) AS limited_timings
            """

            # Add target clause for extra fields
            clause += " ".join(
                [
                    f"""
                        , if(start_target_index > 0, arraySlice({field}s, start_target_index), {field}s) as start_filtered_{field}s
                        , if(end_target_index > 0, arrayResize(start_filtered_{field}s, end_target_index), start_filtered_{field}s) as filtered_{field}s
                        , if(length(filtered_{field}s) > %(event_in_session_limit)s, arrayConcat(arraySlice(filtered_{field}s, 1, intDiv(%(event_in_session_limit)s, 2)), [filtered_{field}s[1+intDiv(%(event_in_session_limit)s, 2)]], arraySlice(filtered_{field}s, (-1)*intDiv(%(event_in_session_limit)s, 2), intDiv(%(event_in_session_limit)s, 2))), filtered_{field}s) AS limited_{field}s
                    """
                    for field in self.extra_event_fields_and_properties
                ]
            )

        else:
            clause, params = super().get_target_clause()

        return clause, params

    def get_path_query_funnel_cte(self, funnel_filter: Filter):
        funnel_persons_generator = ClickhouseFunnelActors(
            funnel_filter,
            self._team,
            include_timestamp=bool(self._filter.funnel_paths),
            include_preceding_timestamp=self._filter.funnel_paths == FUNNEL_PATH_BETWEEN_STEPS,
        )
        (
            funnel_persons_query,
            funnel_persons_param,
        ) = funnel_persons_generator.actor_query(limit_actors=False)
        funnel_persons_query_new_params = funnel_persons_query.replace("%(", "%(funnel_")
        new_funnel_params = {"funnel_" + str(key): val for key, val in funnel_persons_param.items()}
        self.params.update(new_funnel_params)
        return f"""
        WITH {self.event_query.FUNNEL_PERSONS_ALIAS} AS (
            {funnel_persons_query_new_params}
        )
        """

    def get_session_threshold_clause(self) -> str:
        if self.should_query_funnel():
            self._funnel_filter = cast(Filter, self._funnel_filter)  # typing mess

            # TODO: cleanup funnels interval interpolation mess so this can get cleaned up
            if self._funnel_filter.funnel_window_interval:
                funnel_window_interval = self._funnel_filter.funnel_window_interval
                funnel_window_interval_unit = self._funnel_filter.funnel_window_interval_unit_ch()
            elif self._funnel_filter.funnel_window_days:
                funnel_window_interval = self._funnel_filter.funnel_window_days
                funnel_window_interval_unit = "DAY"
            else:
                funnel_window_interval = 14
                funnel_window_interval_unit = "DAY"
            # Not possible to directly compare two interval data types, so using a proxy Date.
            return f"arraySplit(x -> if(toDateTime('2018-01-01') + toIntervalSecond(x.3 / 1000) < toDateTime('2018-01-01') + INTERVAL {funnel_window_interval} {funnel_window_interval_unit}, 0, 1), paths_tuple)"

        return "arraySplit(x -> if(x.3 < %(session_time_threshold)s, 0, 1), paths_tuple)"

    def should_query_funnel(self) -> bool:
        if self._filter.funnel_paths and self._funnel_filter:
            return True
        return False

    def get_array_compacting_function(self) -> Literal["arrayResize", "arraySlice"]:
        if self._filter.end_point:
            return "arrayResize"
        else:
            return "arraySlice"

    def get_filtered_path_ordering(self) -> Tuple[str, ...]:
        fields_to_include = ["filtered_path", "filtered_timings"] + [
            f"filtered_{field}s" for field in self.extra_event_fields_and_properties
        ]

        if self._filter.end_point:
            return tuple([f"arraySlice({field}, (-1) * %(event_in_session_limit)s)" for field in fields_to_include])
        else:
            return tuple([f"arraySlice({field}, 1, %(event_in_session_limit)s)" for field in fields_to_include])
