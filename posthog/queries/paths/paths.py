import dataclasses
from collections import defaultdict
from typing import Dict, List, Literal, Optional, Tuple, Union, cast

from rest_framework.exceptions import ValidationError

from posthog.clickhouse.materialized_columns import ColumnName
from posthog.constants import LIMIT, PATH_EDGE_LIMIT
from posthog.models import Filter, Team
from posthog.models.filters.path_filter import PathFilter
from posthog.models.property import PropertyName
from posthog.queries.insight import insight_sync_execute
from posthog.queries.paths.paths_event_query import PathEventQuery
from posthog.queries.paths.sql import PATH_ARRAY_QUERY
from posthog.queries.util import correct_result_for_sampling

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


class Paths:
    event_query = PathEventQuery
    _filter: PathFilter
    _funnel_filter: Optional[Filter]
    _team: Team
    _extra_event_fields: List[ColumnName]
    _extra_event_properties: List[PropertyName]

    def __init__(self, filter: PathFilter, team: Team, funnel_filter: Optional[Filter] = None) -> None:
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
            self._filter = self._filter.shallow_clone({LIMIT: 100})

        if self._filter.edge_limit is None and not (self._filter.start_point and self._filter.end_point):
            # no edge restriction when both start and end points are defined
            self._filter = self._filter.shallow_clone({PATH_EDGE_LIMIT: EDGE_LIMIT_DEFAULT})

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
                {
                    "source": res[0],
                    "target": res[1],
                    "value": correct_result_for_sampling(
                        res[2],
                        self._filter.sampling_factor,
                    ),
                    "average_conversion_time": res[3],
                }
            )
        return resp

    def _exec_query(self) -> List[Tuple]:
        query = self.get_query()
        return insight_sync_execute(
            query,
            {**self.params, **self._filter.hogql_context.values},
            query_type="paths",
            filter=self._filter,
            team_id=self._team.pk,
        )

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
        path_event_query, params = self.event_query(
            filter=self._filter,
            team=self._team,
            extra_fields=self._extra_event_fields,
            extra_event_properties=self._extra_event_properties,
            person_on_events_mode=self._team.person_on_events_mode,
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

    # Implemented in /ee
    def should_query_funnel(self) -> bool:
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

    # Implemented in /ee
    def get_path_query_funnel_cte(self, funnel_filter: Filter):
        return "", {}

    # Implemented in /ee
    def get_edge_weight_clause(self) -> Tuple[str, Dict]:
        return "", {}

    # Implemented in /ee
    def get_target_point_filter(self) -> str:
        if self._filter.start_point:
            return f"WHERE target_index > 0"
        else:
            return ""

    # Implemented in /ee
    def get_session_threshold_clause(self) -> str:
        return "arraySplit(x -> if(x.3 < %(session_time_threshold)s, 0, 1), paths_tuple)"

    # Implemented in /ee
    def get_target_clause(self) -> Tuple[str, Dict]:
        params: Dict[str, Union[str, None]] = {
            "target_point": None,
            "secondary_target_point": None,
        }

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

        return (clause, params)

    # Implemented in /ee
    def get_array_compacting_function(self) -> Literal["arrayResize", "arraySlice"]:
        return "arraySlice"

    # Implemented in /ee
    def get_filtered_path_ordering(self) -> Tuple[str, ...]:
        fields_to_include = ["filtered_path", "filtered_timings"] + [
            f"filtered_{field}s" for field in self.extra_event_fields_and_properties
        ]

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
