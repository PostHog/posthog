from ctypes import Union
from typing import List

from django.utils import timezone

from posthog.client import sync_execute


def get_agg_events_with_groups_count_for_teams_and_period(
    team_ids: List[Union[str, int]], begin: timezone.datetime, end: timezone.datetime
) -> int:
    result = sync_execute(
        """
        SELECT count(1) as count
        FROM events
        WHERE team_id IN (%(team_id_clause)s)
        AND timestamp between %(begin)s AND %(end)s
        AND ($group_0 != '' OR $group_1 != '' OR $group_2 != '' OR $group_3 != '' OR $group_4 != '')
    """,
        {"team_id_clause": team_ids, "begin": begin, "end": end},
    )[0][0]
    return result
