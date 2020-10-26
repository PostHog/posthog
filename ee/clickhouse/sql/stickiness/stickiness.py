STICKINESS_SQL = """
    SELECT countDistinct(person_id), day_count FROM (
         SELECT person_distinct_id.person_id, countDistinct(toDate(timestamp)) as day_count
         FROM events
         LEFT JOIN (SELECT person_id, distinct_id FROM person_distinct_id WHERE team_id = %(team_id)s) as person_distinct_id ON person_distinct_id.distinct_id = events.distinct_id
         WHERE team_id = {team_id} AND event = '{event}' {filters} {parsed_date_from} {parsed_date_to}
         GROUP BY person_distinct_id.person_id
    ) GROUP BY day_count ORDER BY day_count
"""
