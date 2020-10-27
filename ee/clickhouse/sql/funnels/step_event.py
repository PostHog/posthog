STEP_EVENT_SQL = """
    arrayFilter(
        (timestamp, event, uuid, properties) ->
            {is_first_step} AND
            (team_id = {team_id}) AND
            event = '{event}' {filters} 
        , timestamps, eventsArr, event_ids, event_props
    )[1] AS step_{step}
"""
