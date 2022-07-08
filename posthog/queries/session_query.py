from typing import Dict, Tuple, Union

from posthog.models import Filter
from posthog.models.filters.path_filter import PathFilter
from posthog.models.filters.retention_filter import RetentionFilter
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.models.team import Team
from posthog.queries.util import parse_timestamps


class SessionQuery:
    """
    Query class responsible for creating and joining sessions
    """

    SESSION_TABLE_ALIAS = "sessions"

    _filter: Union[Filter, PathFilter, RetentionFilter, StickinessFilter]
    _team_id: int

    def __init__(self, filter: Union[Filter, PathFilter, RetentionFilter, StickinessFilter], team: Team,) -> None:
        self._filter = filter
        self._team = team

    def get_query(self) -> Tuple[str, Dict]:
        params = {"team_id": self._team.pk}
        parsed_date_from, parsed_date_to, date_params = parse_timestamps(filter=self._filter, team=self._team)
        params.update(date_params)

        return (
            f"""
                SELECT
                    $session_id,
                    dateDiff('second',min(timestamp), max(timestamp)) as session_duration
                FROM
                    events
                WHERE
                    $session_id != ''
                    AND team_id = %(team_id)s
                    {parsed_date_from} - INTERVAL 24 HOUR
                    {parsed_date_to} + INTERVAL 24 HOUR
                GROUP BY $session_id
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
