STEP_EVENT_SQL = """
    arrayFilter(
        (timestamp, event, uuid) ->
            {is_first_step} AND
            (team_id = {team_id}) AND
            event = '{event}' {filters} 
        , timestamps, eventsArr, event_ids
    )[1] AS step_{step}
"""
