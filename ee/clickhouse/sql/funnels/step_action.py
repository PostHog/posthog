STEP_ACTION_SQL = """
    arrayFilter(
        (timestamp, event, uuid {event_prop_param} {distinct_id_param} {person_prop_param}) ->
            {is_first_step} AND
            (team_id = {team_id}) AND
            uuid IN {actions_query} {filters}
        , timestamps, eventsArr, event_ids {event_prop_arg} {distinct_id_arg} {person_prop_arg}
    )[1] AS step_{step}
"""
