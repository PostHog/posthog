import dataclasses
from collections import defaultdict
from re import escape
from typing import Dict, List, Literal, Optional, Tuple, Union, cast

from rest_framework.exceptions import ValidationError

from ee.clickhouse.materialized_columns.columns import ColumnName
from ee.clickhouse.queries.funnels.funnel_persons import ClickhouseFunnelActors
from ee.clickhouse.queries.paths.path_event_query import PathEventQuery
from ee.clickhouse.sql.paths.path import PATH_ARRAY_QUERY
from posthog.client import sync_execute
from posthog.constants import FUNNEL_PATH_BETWEEN_STEPS, LIMIT, PATH_EDGE_LIMIT
from posthog.models import Filter, Team
from posthog.models.filters.path_filter import PathFilter
from posthog.models.property import PropertyName

EVENT_IN_SESSION_LIMIT_DEFAULT = 5
SESSION_TIME_THRESHOLD_DEFAULT = 1800000  # milliseconds to 30 minutes
EDGE_LIMIT_DEFAULT = 50


@dataclasses.dataclass
class ExtraEventClauses:
    final_select_statements: str
    joined_path_tuple_select_statements: str
    array_filter_select_statements: str
    limited_path_tuple_elements: str
    path_time_tuple_select_statements: str
    paths_tuple_elements: str
    group_array_select_statements: str


class ClickhousePaths:
    _filter: PathFilter
    _funnel_filter: Optional[Filter]
    _team: Team
    _extra_event_fields: List[ColumnName]
    _extra_event_properties: List[PropertyName]

    def __init__(self, filter: PathFilter, team: Team, funnel_filter: Optional[Filter] = None,) -> None:
        self._filter = filter
        self._team = team
        self.params = {
            "team_id": self._team.pk,
            "event_in_session_limit": self._filter.step_limit or EVENT_IN_SESSION_LIMIT_DEFAULT,
            "session_time_threshold": SESSION_TIME_THRESHOLD_DEFAULT,
            "groupings": self._filter.path_groupings or None,
            "regex_groupings": None,
        }
        self._funnel_filter = funnel_filter

        self._extra_event_fields: List[ColumnName] = []
        self._extra_event_properties: List[PropertyName] = []
        if self._filter.include_recordings:
            self._extra_event_fields = ["uuid", "timestamp"]
            self._extra_event_properties = ["$session_id", "$window_id"]

        if self._filter.include_all_custom_events and self._filter.custom_events:
            raise ValidationError("Cannot include all custom events and specific custom events in the same query")

        if not self._filter.limit:
            self._filter = self._filter.with_data({LIMIT: 100})

        if self._filter.path_groupings:
            regex_groupings = []
            for grouping in self._filter.path_groupings:
                regex_grouping = escape(grouping)
                # don't allow arbitrary regex for now
                regex_grouping = regex_grouping.replace("\\*", ".*")
                regex_groupings.append(regex_grouping)
            self.params["regex_groupings"] = regex_groupings

        if self._filter.edge_limit is None and not (self._filter.start_point and self._filter.end_point):
            # no edge restriction when both start and end points are defined
            self._filter = self._filter.with_data({PATH_EDGE_LIMIT: EDGE_LIMIT_DEFAULT})

        if (
            self._filter.max_edge_weight
            and self._filter.min_edge_weight
            and self._filter.max_edge_weight < self._filter.min_edge_weight
        ):
            raise ValidationError("Max Edge weight can't be lower than min edge weight")

    def run(self, *args, **kwargs):
        results = self._exec_query()

        if not self._filter.min_edge_weight and not self._filter.max_edge_weight:
            results = self.validate_results(results)

        return self._format_results(results)

    def _format_results(self, results):
        if not results or len(results) == 0:
            return []

        resp = []
        for res in results:
            resp.append(
                {"source": res[0], "target": res[1], "value": res[2], "average_conversion_time": res[3],}
            )
        return resp

    def _exec_query(self) -> List[Tuple]:
        query = self.get_query()
        return sync_execute(query, self.params)

    def get_query(self) -> str:

        path_query = self.get_path_query()
        funnel_cte = ""

        if self.should_query_funnel():
            funnel_cte = self.get_path_query_funnel_cte(cast(Filter, self._funnel_filter))

        return funnel_cte + path_query

    @property
    def extra_event_fields_and_properties(self):
        return self._extra_event_fields + self._extra_event_properties

    # Returns the set of clauses used to select the uuid, timestamp, session_id and window_id for the events in the query
    # These values are used to identify the recordings shown in the person modal
    def get_extra_event_clauses(self) -> ExtraEventClauses:
        final_select_statements = " ".join(
            [f"final_{field} as {field}," for field in self.extra_event_fields_and_properties]
        )
        joined_path_tuple_select_statements = " ".join(
            [
                # +4 because clickhouse tuples are indexed from 1 and there are already 3 elements in the tuple
                f", joined_path_tuple.{index+4} as final_{field}"
                for index, field in enumerate(self.extra_event_fields_and_properties)
            ]
        )
        array_filter_select_statements = " ".join(
            [
                f", arrayFilter((x,y)->y, {field}, mapping) as {field}s"
                for field in self.extra_event_fields_and_properties
            ]
        )
        limited_path_tuple_elements = " ".join(
            [f", limited_{field}s" for field in self.extra_event_fields_and_properties]
        )
        path_time_tuple_select_statements = " ".join(
            [
                # +4 because clickhouse tuples are indexed from 1 and there are already 3 elements in the tuple
                f", path_time_tuple.{index+4} as {field}"
                for index, field in enumerate(self.extra_event_fields_and_properties)
            ]
        )
        paths_tuple_elements = " ".join([f", {field}s" for field in self.extra_event_fields_and_properties])
        group_array_select_statements = " ".join(
            [f"groupArray({field}) as {field}s," for field in self.extra_event_fields_and_properties]
        )

        return ExtraEventClauses(
            final_select_statements=final_select_statements,
            joined_path_tuple_select_statements=joined_path_tuple_select_statements,
            array_filter_select_statements=array_filter_select_statements,
            limited_path_tuple_elements=limited_path_tuple_elements,
            path_time_tuple_select_statements=path_time_tuple_select_statements,
            paths_tuple_elements=paths_tuple_elements,
            group_array_select_statements=group_array_select_statements,
        )

    def get_paths_per_person_query(self) -> str:
        path_event_query, params = PathEventQuery(
            filter=self._filter,
            team=self._team,
            extra_fields=self._extra_event_fields,
            extra_event_properties=self._extra_event_properties,
        ).get_query()
        self.params.update(params)

        boundary_event_filter = self.get_target_point_filter()
        target_clause, target_params = self.get_target_clause()
        self.params.update(target_params)

        session_threshold_clause = self.get_session_threshold_clause()

        extra_event_clauses = self.get_extra_event_clauses()

        return PATH_ARRAY_QUERY.format(
            path_event_query=path_event_query,
            boundary_event_filter=boundary_event_filter,
            target_clause=target_clause,
            session_threshold_clause=session_threshold_clause,
            extra_final_select_statements=extra_event_clauses.final_select_statements,
            extra_joined_path_tuple_select_statements=extra_event_clauses.joined_path_tuple_select_statements,
            extra_array_filter_select_statements=extra_event_clauses.array_filter_select_statements,
            extra_limited_path_tuple_elements=extra_event_clauses.limited_path_tuple_elements,
            extra_path_time_tuple_select_statements=extra_event_clauses.path_time_tuple_select_statements,
            extra_paths_tuple_elements=extra_event_clauses.paths_tuple_elements,
            extra_group_array_select_statements=extra_event_clauses.group_array_select_statements,
        )

    def should_query_funnel(self) -> bool:
        if self._filter.funnel_paths and self._funnel_filter:
            return True
        return False

    def get_path_query(self) -> str:

        paths_per_person_query = self.get_paths_per_person_query()

        self.params["edge_limit"] = self._filter.edge_limit

        edge_weight_filter, edge_weight_params = self.get_edge_weight_clause()
        self.params.update(edge_weight_params)

        return f"""
            SELECT last_path_key as source_event,
                path_key as target_event,
                COUNT(*) AS event_count,
                avg(conversion_time) AS average_conversion_time
            FROM ({paths_per_person_query})
            WHERE source_event IS NOT NULL
            GROUP BY source_event,
                    target_event
            {edge_weight_filter}
            ORDER BY event_count DESC,
                    source_event,
                    target_event
            {'LIMIT %(edge_limit)s' if self._filter.edge_limit else ''}
        """

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
        WITH {PathEventQuery.FUNNEL_PERSONS_ALIAS} AS (
            {funnel_persons_query_new_params}
        )
        """

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

    def get_target_clause(self) -> Tuple[str, Dict]:
        params: Dict[str, Union[str, None]] = {"target_point": None, "secondary_target_point": None}

        if self._filter.end_point and self._filter.start_point:
            params.update({"target_point": self._filter.end_point, "secondary_target_point": self._filter.start_point})

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

            return (
                clause,
                params,
            )
        else:
            filtered_path_ordering_clause = self.get_filtered_path_ordering()
            compacting_function = self.get_array_compacting_function()
            params.update({"target_point": self._filter.end_point or self._filter.start_point})

            clause = f"""
            , indexOf(compact_path, %(target_point)s) as target_index
            , if(target_index > 0, {compacting_function}(compact_path, target_index), compact_path) as filtered_path
            , if(target_index > 0, {compacting_function}(timings, target_index), timings) as filtered_timings
            , {filtered_path_ordering_clause[0]} as limited_path
            , {filtered_path_ordering_clause[1]} as limited_timings
            """

            # Add target clause for extra fields
            clause += " ".join(
                [
                    f"""
                        , if(target_index > 0, {compacting_function}({field}s, target_index), {field}s) as filtered_{field}s
                        , {filtered_path_ordering_clause[index+2]} as limited_{field}s
                    """
                    for index, field in enumerate(self.extra_event_fields_and_properties)
                ]
            )

            return (
                clause,
                params,
            )

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

    def validate_results(self, results):
        # Query guarantees results list to be:
        # 1. Directed, Acyclic Tree where each node has only 1 child
        # 2. All start nodes beginning with 1_

        seen = set()  # source nodes that've been traversed
        edges = defaultdict(list)
        validated_results = []
        starting_nodes_stack = []

        for result in results:
            edges[result[0]].append(result[1])
            if result[0].startswith("1_"):
                # All nodes with 1_ are valid starting nodes
                starting_nodes_stack.append(result[0])

        while starting_nodes_stack:
            current_node = starting_nodes_stack.pop()
            seen.add(current_node)

            for node in edges[current_node]:
                if node not in seen:
                    starting_nodes_stack.append(node)

        for result in results:
            if result[0] in seen:
                validated_results.append(result)

        return validated_results
