STEP_ACTION_SQL = """
    arrayFilter(
        (timestamp, event, random_event_id) ->
            {is_first_step} AND
            (team_id = {team_id}) AND
            random_event_id IN ({actions_query}) {filters}
        , timestamps, eventsArr, event_ids
    )[1] AS step_{step}
"""
