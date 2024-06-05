PERSON_DISTINCT_ID_OVERRIDES_JOIN_SQL = """LEFT OUTER JOIN (
    SELECT
        argMax(person_distinct_id_overrides.person_id, person_distinct_id_overrides.version) AS person_id,
        person_distinct_id_overrides.distinct_id AS distinct_id
     FROM person_distinct_id_overrides
     WHERE equals(person_distinct_id_overrides.team_id, %(team_id)s)
     GROUP BY person_distinct_id_overrides.distinct_id
     HAVING ifNull(equals(argMax(person_distinct_id_overrides.is_deleted, person_distinct_id_overrides.version), 0), 0)
) AS {person_overrides_table_alias}
ON {event_table_alias}.distinct_id = {person_overrides_table_alias}.distinct_id"""
