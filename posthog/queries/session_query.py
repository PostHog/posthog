from typing import Dict, Optional, Tuple, Union

from dateutil.parser import parse

from posthog.models import Filter
from posthog.models.filters.path_filter import PathFilter
from posthog.models.filters.retention_filter import RetentionFilter
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.models.team import Team
from posthog.queries.query_date_range import QueryDateRange


class SessionQuery:
    """
    Query class responsible for creating and joining sessions
    """

    SESSION_TABLE_ALIAS = "sessions"

    _filter: Union[Filter, PathFilter, RetentionFilter, StickinessFilter]
    _team_id: int
    _session_id_alias: Optional[str]

    def __init__(
        self,
        filter: Union[Filter, PathFilter, RetentionFilter, StickinessFilter],
        team: Team,
        session_id_alias=None,
    ) -> None:
        self._filter = filter
        self._team = team
        self._session_id_alias = session_id_alias
        # the session_replay_events table couldn't have existed before this date in any instance of PostHog
        self._can_use_session_replay_events = self._filter.date_from and self._filter.date_from > parse(
            "2023-05-10T00:00:00Z"
        )

    def get_query(self) -> Tuple[str, Dict]:
        params = {"team_id": self._team.pk}

        query_date_range = QueryDateRange(filter=self._filter, team=self._team, should_round=False)
        parsed_date_from, date_from_params = query_date_range.date_from
        parsed_date_to, date_to_params = query_date_range.date_to
        params.update(date_from_params)
        params.update(date_to_params)

        column_to_select = "$session_id"
        timestamp_from_column = "timestamp"
        timestamp_to_column = "timestamp"
        check_for_empty_sessions = f"AND {self._session_id_alias or '$session_id'} != ''"
        table = "events"
        if self._can_use_session_replay_events:
            parsed_date_from = parsed_date_from.replace("timestamp", "min_first_timestamp")
            parsed_date_to = parsed_date_to.replace("timestamp", "max_last_timestamp")
            column_to_select = "session_id"
            self._session_id_alias = "$session_id"
            timestamp_from_column = "min_first_timestamp"
            timestamp_to_column = "max_last_timestamp"
            check_for_empty_sessions = ""
            table = "session_replay_events"

        return (
            f"""
                SELECT
                    {column_to_select}{f" AS {self._session_id_alias}" if self._session_id_alias else ""},
                    dateDiff('second',min({timestamp_from_column}), max({timestamp_to_column})) as session_duration
                FROM
                    {table}
                WHERE team_id = %(team_id)s
                    {parsed_date_from} - INTERVAL 24 HOUR
                    {parsed_date_to} + INTERVAL 24 HOUR
                    {check_for_empty_sessions}
                GROUP BY {self._session_id_alias or "$session_id"}
            """,
            params,
        )

    @property
    def is_used(self):
        "Returns whether any columns from session are actually being queried"
        if (
            not isinstance(self._filter, StickinessFilter) and self._filter.breakdown_type == "session"
        ):  # stickiness doesn't have breakdown_type
            return True

        if any(prop.type == "session" for prop in self._filter.property_groups.flat):
            return True
        if any(prop.type == "session" for entity in self._filter.entities for prop in entity.property_groups.flat):
            return True

        if any(entity.math_property == "$session_duration" for entity in self._filter.entities):
            # TODO: generalise this to work for math_property_type, not just sessions, when we add more properties
            return True

        return False
