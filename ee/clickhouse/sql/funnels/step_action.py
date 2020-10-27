STEP_ACTION_SQL = """
    arrayFilter(
        (timestamp, event, uuid, properties) ->
            {is_first_step} AND
            (team_id = {team_id}) AND
            uuid IN ({actions_query}) {filters}
        , timestamps, eventsArr, event_ids, event_props
    )[1] AS step_{step}
"""
