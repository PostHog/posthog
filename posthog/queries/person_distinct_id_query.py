from posthog.models.event.new_events_schema import events_read_table
from posthog.models.person.sql import GET_TEAM_PERSON_DISTINCT_IDS


# TODO: Remove the `team_id` param, which is no longer needed – we do all the value interpolation at query time
def get_team_distinct_ids_query(
    team_id: int, *, relevant_events_conditions: str = "", use_new_events_schema: bool = False
) -> str:
    events_table = events_read_table(use_new_events_schema)
    relevant_events_filter = (
        f"AND distinct_id IN (SELECT distinct_id FROM {events_table} WHERE team_id = %(team_id)s {relevant_events_conditions})"
        if relevant_events_conditions
        else ""
    )

    return GET_TEAM_PERSON_DISTINCT_IDS.format(relevant_events_filter=relevant_events_filter)
