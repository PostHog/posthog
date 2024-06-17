from typing import Any

from posthog.constants import (
    FUNNEL_PATH_AFTER_STEP,
    FUNNEL_PATH_BEFORE_STEP,
    FUNNEL_PATH_BETWEEN_STEPS,
    PAGEVIEW_EVENT,
    SCREEN_EVENT,
    HOGQL,
)
from posthog.hogql.hogql import translate_hogql
from posthog.models.filters.path_filter import PathFilter
from posthog.models.property.util import get_property_string_expr
from posthog.models.team import Team
from posthog.queries.event_query import EventQuery
from posthog.queries.util import get_person_properties_mode
from posthog.schema import PersonsOnEventsMode


class PathEventQuery(EventQuery):
    FUNNEL_PERSONS_ALIAS = "funnel_actors"
    _filter: PathFilter

    def get_query(self) -> tuple[str, dict[str, Any]]:
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
            funnel_paths_join = (
                f"JOIN {self.FUNNEL_PERSONS_ALIAS} ON {self.FUNNEL_PERSONS_ALIAS}.actor_id = {self._person_id_alias}"
            )
            funnel_paths_filter = f"AND {self.EVENT_TABLE_ALIAS}.timestamp {operator} target_timestamp {funnel_window if self._filter.funnel_paths == FUNNEL_PATH_BEFORE_STEP and self._filter.funnel_step and self._filter.funnel_step < 0 else ''}"
        elif self._filter.funnel_paths == FUNNEL_PATH_BETWEEN_STEPS:
            funnel_paths_timestamp = f"{self.FUNNEL_PERSONS_ALIAS}.min_timestamp as min_timestamp, {self.FUNNEL_PERSONS_ALIAS}.max_timestamp as max_timestamp"
            funnel_paths_join = (
                f"JOIN {self.FUNNEL_PERSONS_ALIAS} ON {self.FUNNEL_PERSONS_ALIAS}.actor_id = {self._person_id_alias}"
            )
            funnel_paths_filter = f"AND {self.EVENT_TABLE_ALIAS}.timestamp >= min_timestamp AND {self.EVENT_TABLE_ALIAS}.timestamp <= max_timestamp"

        # We don't use ColumnOptimizer to decide what to query because Paths query doesn't surface any filter properties

        _fields = [
            f"{self.EVENT_TABLE_ALIAS}.timestamp AS timestamp",
            f"{self._person_id_alias} AS person_id",
            funnel_paths_timestamp,
        ]
        _fields += [f"{self.EVENT_TABLE_ALIAS}.{field} AS {field}" for field in self._extra_fields]
        _fields += [
            get_property_string_expr(
                "events",
                field,
                f"'{field}'",
                "properties",
                table_alias=self.EVENT_TABLE_ALIAS,
            )[0]
            + f" as {field}"
            for field in self._extra_event_properties
        ]

        event_hogql = "event"

        if self._should_query_hogql():
            event_hogql = self._filter.paths_hogql_expression or event_hogql
        if self._should_query_url():
            event_hogql = f"if(event = '{PAGEVIEW_EVENT}', replaceRegexpAll(ifNull(properties.$current_url, ''), '(.)/$', '\\\\1'), {event_hogql})"
        if self._should_query_screen():
            event_hogql = f"if(event = '{SCREEN_EVENT}', properties.$screen_name, {event_hogql})"

        event_conditional = (
            "ifNull("
            + translate_hogql(
                query=event_hogql,
                context=self._filter.hogql_context,
                dialect="clickhouse",
                events_table_alias=self.EVENT_TABLE_ALIAS,
            )
            + ", '') AS path_item_ungrouped"
        )

        _fields.append(event_conditional)

        grouping_fields, grouping_params = self._get_grouping_fields()
        _fields.extend(grouping_fields)
        self.params.update(grouping_params)

        # remove empty strings
        _fields = list(filter(None, _fields))

        date_query, date_params = self._get_date_filter()
        self.params.update(date_params)

        prop_query, prop_params = self._get_prop_groups(
            self._filter.property_groups,
            person_properties_mode=get_person_properties_mode(self._team),
            person_id_joined_alias=self._person_id_alias,
        )

        self.params.update(prop_params)

        event_query, event_params = self._get_event_query(deep_filtering=False)
        self.params.update(event_params)

        person_query, person_params = self._get_person_query()
        self.params.update(person_params)

        groups_query, groups_params = self._get_groups_query()
        self.params.update(groups_params)

        null_person_filter = (
            f"AND notEmpty({self.EVENT_TABLE_ALIAS}.person_id)"
            if self._person_on_events_mode != PersonsOnEventsMode.DISABLED
            else ""
        )

        sample_clause = "SAMPLE %(sampling_factor)s" if self._filter.sampling_factor else ""
        self.params.update({"sampling_factor": self._filter.sampling_factor})

        query = f"""
            SELECT {','.join(_fields)} FROM events {self.EVENT_TABLE_ALIAS}
            {sample_clause}
            {self._get_person_ids_query(relevant_events_conditions=f"{self._get_event_query(deep_filtering=True)[0]} {date_query}")}
            {person_query}
            {groups_query}
            {funnel_paths_join}
            WHERE team_id = %(team_id)s
            {event_query}
            {date_query}
            {prop_query}
            {funnel_paths_filter}
            {null_person_filter}
            ORDER BY {self._person_id_alias}, {self.EVENT_TABLE_ALIAS}.timestamp
        """
        return query, self.params

    def _determine_should_join_distinct_ids(self) -> None:
        if self._person_on_events_mode == PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS:
            self._should_join_distinct_ids = False
        else:
            self._should_join_distinct_ids = True

    def _determine_should_join_persons(self) -> None:
        EventQuery._determine_should_join_persons(self)
        if self._person_on_events_mode != PersonsOnEventsMode.DISABLED:
            self._should_join_persons = False

    def _get_grouping_fields(self) -> tuple[list[str], dict[str, Any]]:
        _fields = []
        params = {}

        team: Team = Team.objects.get(pk=self._team_id)

        replacements = []

        if self._filter.path_replacements and team.path_cleaning_filters and len(team.path_cleaning_filters) > 0:
            replacements.extend(team.path_cleaning_filters)

        if self._filter.local_path_cleaning_filters and len(self._filter.local_path_cleaning_filters) > 0:
            replacements.extend(self._filter.local_path_cleaning_filters)

        # If there are any path cleaning rules, apply them
        if len(replacements) > 0:
            final_path_item_column = "path_item_cleaned"
            for idx, replacement in enumerate(replacements):
                alias = replacement["alias"]
                regex = replacement["regex"]
                source_path_item_column = "path_item_ungrouped" if idx == 0 else f"path_item_{idx-1}"
                result_path_item_column = "path_item_cleaned" if idx == len(replacements) - 1 else f"path_item_{idx}"
                _fields.append(
                    f"replaceRegexpAll({source_path_item_column}, %(regex_replacement_{idx})s, %(alias_{idx})s) "
                    f"AS {result_path_item_column}"
                )
                params[f"regex_replacement_{idx}"] = regex
                params[f"alias_{idx}"] = alias
        else:
            final_path_item_column = "path_item_ungrouped"

        # Match wildcard groups
        _fields.append(f"multiMatchAnyIndex({final_path_item_column}, %(regex_groupings)s) AS group_index")
        _fields.append(f"if(group_index > 0, %(groupings)s[group_index], {final_path_item_column}) AS path_item")

        return _fields, params

    def _get_event_query(self, deep_filtering: bool) -> tuple[str, dict[str, Any]]:
        params: dict[str, Any] = {}

        conditions = []
        or_conditions = []
        if self._filter.include_pageviews:
            or_conditions.append(f"event = '{PAGEVIEW_EVENT}'")

        if self._filter.include_screenviews:
            or_conditions.append(f"event = '{SCREEN_EVENT}'")

        if self._filter.include_all_custom_events:
            or_conditions.append(f"NOT event LIKE '$%%'")

        if self._filter.include_hogql:
            or_conditions.append(f"1 = 1")

        if self._filter.custom_events:
            or_conditions.append(f"event IN %(custom_events)s")
            params["custom_events"] = self._filter.custom_events

        if or_conditions:
            conditions.append(f"({' OR '.join(or_conditions)})")

        if not deep_filtering and self._filter.exclude_events:  # We don't have path_item in deep filtering
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

    def _should_query_hogql(self) -> bool:
        if (
            self._filter.target_events == [] and self._filter.custom_events == []
        ) and HOGQL not in self._filter.exclude_events:
            return True
        elif self._filter.include_hogql:
            return True

        return False
