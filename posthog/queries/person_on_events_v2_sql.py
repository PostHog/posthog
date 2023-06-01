PERSON_OVERRIDES_JOIN_SQL = """LEFT OUTER JOIN (
    SELECT argMax(override_person_id, version) as person_id, old_person_id
    FROM person_overrides
    WHERE team_id = %(team_id)s
    GROUP BY old_person_id
) AS {person_overrides_table_alias}
ON {event_table_alias}.person_id = {person_overrides_table_alias}.old_person_id"""
