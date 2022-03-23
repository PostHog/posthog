from typing import Any, Dict, List, Tuple

from ee.clickhouse.models.property import get_property_string_expr
from ee.clickhouse.queries.event_query import EnterpriseEventQuery
from posthog.constants import (
    FUNNEL_PATH_AFTER_STEP,
    FUNNEL_PATH_BEFORE_STEP,
    FUNNEL_PATH_BETWEEN_STEPS,
    PAGEVIEW_EVENT,
    SCREEN_EVENT,
)
from posthog.models.filters.path_filter import PathFilter
from posthog.models.team import Team


class PathEventQuery(EnterpriseEventQuery):
    FUNNEL_PERSONS_ALIAS = "funnel_actors"
    _filter: PathFilter

    def get_query(self) -> Tuple[str, Dict[str, Any]]:

        funnel_paths_timestamp = ""
        funnel_paths_join = ""
        funnel_paths_filter = ""

        if self._filter.funnel_paths == FUNNEL_PATH_AFTER_STEP or self._filter.funnel_paths == FUNNEL_PATH_BEFORE_STEP:
            # used when looking for paths up to a dropoff point to account for events happening between the latest even and when the person is deemed dropped off
            funnel_window = (
                f"+ INTERVAL {self._filter.funnel_window_interval} {self._filter.funnel_window_interval_unit_ch()}"
            )
            operator = ">=" if self._filter.funnel_paths == FUNNEL_PATH_AFTER_STEP else "<="

            funnel_paths_timestamp = f"{self.FUNNEL_PERSONS_ALIAS}.timestamp AS target_timestamp"
            funnel_paths_join = f"JOIN {self.FUNNEL_PERSONS_ALIAS} ON {self.FUNNEL_PERSONS_ALIAS}.actor_id = {self.DISTINCT_ID_TABLE_ALIAS}.person_id"
            funnel_paths_filter = f"AND {self.EVENT_TABLE_ALIAS}.timestamp {operator} target_timestamp {funnel_window if self._filter.funnel_paths == FUNNEL_PATH_BEFORE_STEP and self._filter.funnel_step and self._filter.funnel_step < 0 else ''}"
        elif self._filter.funnel_paths == FUNNEL_PATH_BETWEEN_STEPS:
            funnel_paths_timestamp = f"{self.FUNNEL_PERSONS_ALIAS}.min_timestamp as min_timestamp, {self.FUNNEL_PERSONS_ALIAS}.max_timestamp as max_timestamp"
            funnel_paths_join = f"JOIN {self.FUNNEL_PERSONS_ALIAS} ON {self.FUNNEL_PERSONS_ALIAS}.actor_id = {self.DISTINCT_ID_TABLE_ALIAS}.person_id"
            funnel_paths_filter = f"AND {self.EVENT_TABLE_ALIAS}.timestamp >= min_timestamp AND {self.EVENT_TABLE_ALIAS}.timestamp <= max_timestamp"

        # We don't use ColumnOptimizer to decide what to query because Paths query doesn't surface any filter properties
        _fields = [
            f"{self.EVENT_TABLE_ALIAS}.timestamp AS timestamp",
            f"{self.DISTINCT_ID_TABLE_ALIAS}.person_id as person_id" if self._should_join_distinct_ids else "",
            funnel_paths_timestamp,
        ]
        _fields += [f"{self.EVENT_TABLE_ALIAS}.{field} AS {field}" for field in self._extra_fields]
        _fields += [
            get_property_string_expr("events", field, f"'{field}'", "properties", table_alias=self.EVENT_TABLE_ALIAS)[0]
            + f" as {field}"
            for field in self._extra_event_properties
        ]

        event_conditional = (
            f"if({self.EVENT_TABLE_ALIAS}.event = '{SCREEN_EVENT}', {self._get_screen_name_parsing()}, "
            if self._should_query_screen()
            else "if(0, '', "
        )
        event_conditional += (
            f"if({self.EVENT_TABLE_ALIAS}.event = '{PAGEVIEW_EVENT}', {self._get_current_url_parsing()}, "
            if self._should_query_url()
            else "if(0, '', "
        )
        event_conditional += f"{self.EVENT_TABLE_ALIAS}.event)) AS path_item_ungrouped"

        _fields.append(event_conditional)

        grouping_fields, grouping_params = self._get_grouping_fields()
        _fields.extend(grouping_fields)
        self.params.update(grouping_params)

        # remove empty strings
        _fields = list(filter(None, _fields))

        date_query, date_params = self._get_date_filter()
        self.params.update(date_params)

        prop_query, prop_params = self._get_prop_groups(self._filter.property_groups)

        self.params.update(prop_params)

        event_query, event_params = self._get_event_query()
        self.params.update(event_params)

        person_query, person_params = self._get_person_query()
        self.params.update(person_params)

        groups_query, groups_params = self._get_groups_query()
        self.params.update(groups_params)

        query = f"""
            SELECT {','.join(_fields)} FROM events {self.EVENT_TABLE_ALIAS}
            {self._get_distinct_id_query()}
            {person_query}
            {groups_query}
            {funnel_paths_join}
            WHERE team_id = %(team_id)s
            {event_query}
            {date_query}
            {prop_query}
            {funnel_paths_filter}
            ORDER BY {self.DISTINCT_ID_TABLE_ALIAS}.person_id, {self.EVENT_TABLE_ALIAS}.timestamp
        """
        return query, self.params

    def _determine_should_join_distinct_ids(self) -> None:
        self._should_join_distinct_ids = True

    def _get_grouping_fields(self) -> Tuple[List[str], Dict[str, Any]]:
        _fields = []
        params = {}

        team: Team = Team.objects.get(pk=self._team_id)

        replacements = []

        if self._filter.path_replacements and team.path_cleaning_filters and len(team.path_cleaning_filters) > 0:
            replacements.extend(team.path_cleaning_filters)

        if self._filter.local_path_cleaning_filters and len(self._filter.local_path_cleaning_filters) > 0:
            replacements.extend(self._filter.local_path_cleaning_filters)

        if len(replacements) > 0:
            for idx, replacement in enumerate(replacements):
                alias = replacement["alias"]
                regex = replacement["regex"]
                if idx == 0:
                    name = "path_item" if idx == len(replacements) - 1 else f"path_item_{idx}"
                    _fields.append(
                        f"replaceRegexpAll(path_item_ungrouped, %(regex_replacement_{idx})s, %(alias_{idx})s) as {name}"
                    )
                elif idx == len(replacements) - 1:
                    _fields.append(
                        f"replaceRegexpAll(path_item_{idx - 1}, %(regex_replacement_{idx})s, %(alias_{idx})s) as path_item"
                    )
                else:
                    _fields.append(
                        f"replaceRegexpAll(path_item_{idx - 1}, %(regex_replacement_{idx})s, %(alias_{idx})s) as path_item_{idx}"
                    )
                params[f"regex_replacement_{idx}"] = regex
                params[f"alias_{idx}"] = alias

        else:
            _fields.append("multiMatchAnyIndex(path_item_ungrouped, %(regex_groupings)s) AS group_index")
            _fields.append("if(group_index > 0, %(groupings)s[group_index], path_item_ungrouped) AS path_item")

        return _fields, params

    def _get_current_url_parsing(self):
        path_type, _ = get_property_string_expr("events", "$current_url", "'$current_url'", "properties")
        return f"if(length({path_type}) > 1, replaceRegexpAll({path_type}, '/$', ''), {path_type})"

    def _get_screen_name_parsing(self):
        path_type, _ = get_property_string_expr("events", "$screen_name", "'$screen_name'", "properties")
        return path_type

    def _get_event_query(self) -> Tuple[str, Dict[str, Any]]:
        params: Dict[str, Any] = {}

        conditions = []
        or_conditions = []
        if self._filter.include_pageviews:
            or_conditions.append(f"event = '{PAGEVIEW_EVENT}'")

        if self._filter.include_screenviews:
            or_conditions.append(f"event = '{SCREEN_EVENT}'")

        if self._filter.include_all_custom_events:
            or_conditions.append(f"NOT event LIKE '$%%'")

        if self._filter.custom_events:
            or_conditions.append(f"event IN %(custom_events)s")
            params["custom_events"] = self._filter.custom_events

        if or_conditions:
            conditions.append(f"({' OR '.join(or_conditions)})")

        if self._filter.exclude_events:
            conditions.append(f"NOT path_item IN %(exclude_events)s")
            params["exclude_events"] = self._filter.exclude_events

        if conditions:
            return f" AND {' AND '.join(conditions)}", params

        return "", {}

    def _should_query_url(self) -> bool:
        if (
            self._filter.target_events == [] and self._filter.custom_events == []
        ) and PAGEVIEW_EVENT not in self._filter.exclude_events:
            return True
        elif self._filter.include_pageviews:
            return True

        return False

    def _should_query_screen(self) -> bool:
        if (
            self._filter.target_events == [] and self._filter.custom_events == []
        ) and SCREEN_EVENT not in self._filter.exclude_events:
            return True
        elif self._filter.include_screenviews:
            return True

        return False
