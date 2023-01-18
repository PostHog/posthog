from typing import Any, Dict, Tuple

from posthog.models.person.sql import GET_TEAM_PERSON_DISTINCT_IDS


def get_team_distinct_ids_query(team_id: int) -> Tuple[str, Dict[str, Any]]:
    return GET_TEAM_PERSON_DISTINCT_IDS, {"team_id": team_id}
