from posthog.models.person.sql import GET_TEAM_PERSON_DISTINCT_IDS
from typing import Tuple, Dict, Any


def get_team_distinct_ids_query(team_id: int) -> Tuple[str, Dict[str, Any]]:

    return GET_TEAM_PERSON_DISTINCT_IDS, {"team_id": team_id}
