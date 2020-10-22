FUNNEL_SQL = """
SELECT id, {select_steps} FROM (
    SELECT 
        person_distinct_id.person_id as id,
        groupArray(events.timestamp) as timestamps,
        groupArray(events.event) as eventsArr,
        groupArray(events.uuid) as event_ids,
        {steps}
    FROM events 
    JOIN person_distinct_id ON person_distinct_id.distinct_id = events.distinct_id
    WHERE team_id = {team_id} {filters} {parsed_date_from} {parsed_date_to}
    GROUP BY person_distinct_id.person_id, team_id
    ORDER BY timestamps
 ) WHERE step_0 <> toDateTime(0)
"""
