from typing import Dict, Optional, Tuple, cast

from ee.clickhouse.queries.actor_base_query import ActorBaseQuery
from ee.clickhouse.queries.paths.paths import ClickhousePaths
from posthog.models.filters.filter import Filter


class ClickhousePathsActors(ClickhousePaths, ActorBaseQuery):  # type: ignore
    """
    `path_start_key`, `path_end_key`, and `path_dropoff_key` are three new params for this class.
    These determine the start and end point of Paths you want. All of these are optional.

    Not specifying them means "get me all users on this path query".

    Only specifying `path_start_key` means "get me all users whose paths start at this key"
    Only specifying `path_end_key` means "get me all users whose paths end at this key"

    Specifying both means "get me all users whose path starts at `start_key` and ends at `end_key`."

    Specifying `path_dropoff_key` means "get me users who dropped off after this key. If you specify
    this key, the other two keys are invalid

    Note that:
        Persons are calculated only between direct paths. There should not be any
        other path item between start and end key.
    """

    def actor_query(self, limit_actors: Optional[bool] = True) -> Tuple[str, Dict]:
        paths_per_person_query = self.get_paths_per_person_query()
        person_path_filter = self.get_person_path_filter()
        paths_funnel_cte = ""

        if self.should_query_funnel():
            paths_funnel_cte = self.get_path_query_funnel_cte(cast(Filter, self._funnel_filter))

        select_statement = "DISTINCT person_id AS actor_id"
        group_statement = ""
        if self._filter.include_recordings:
            select_statement = """
                person_id AS actor_id
                , groupUniqArray(10)((timestamp, uuid, $session_id, $window_id)) as matching_events
            """
            group_statement = "GROUP BY person_id"

        self.params["limit"] = self._filter.limit
        self.params["offset"] = self._filter.offset

        return (
            f"""
            {paths_funnel_cte}
            SELECT
            {select_statement}
            FROM (
                {paths_per_person_query}
            )
            WHERE {person_path_filter}
            {group_statement}
            ORDER BY person_id
            {"LIMIT %(limit)s" if limit_actors else ""}
            {"OFFSET %(offset)s" if limit_actors else ""}
        """,
            self.params,
        )

    def get_person_path_filter(self) -> str:
        conditions = []

        if self._filter.path_dropoff_key:
            conditions.append("path_dropoff_key = %(path_dropoff_key)s AND path_dropoff_key = path_key")
            self.params["path_dropoff_key"] = self._filter.path_dropoff_key
        else:
            if self._filter.path_start_key:
                conditions.append("last_path_key = %(path_start_key)s")
                self.params["path_start_key"] = self._filter.path_start_key

            if self._filter.path_end_key:
                conditions.append("path_key = %(path_end_key)s")
                self.params["path_end_key"] = self._filter.path_end_key

        if conditions:
            return " AND ".join(conditions)

        return "1=1"
