DELETE_PERSON_BY_ID = """
INSERT INTO person (id, created_at, team_id, properties, is_identified, _timestamp, _offset, is_deleted) SELECT %(id)s, %(created_at)s, %(team_id)s, %(properties)s, %(is_identified)s, %(_timestamp)s, 0, 1
"""

DELETE_PERSON_EVENTS_BY_ID = """
ALTER TABLE events DELETE
WHERE distinct_id IN (
    SELECT distinct_id FROM person_distinct_id WHERE person_id=%(id)s AND team_id = %(team_id)s
)
AND team_id = %(team_id)s
"""

INSERT_PERSON_DISTINCT_ID = """
INSERT INTO person_distinct_id SELECT %(distinct_id)s, %(person_id)s, %(team_id)s, %(_sign)s, now(), 0 VALUES
"""

INSERT_PERSON_DISTINCT_ID2 = """
INSERT INTO person_distinct_id2 (distinct_id, person_id, team_id, is_deleted, version, _timestamp, _offset, _partition) SELECT %(distinct_id)s, %(person_id)s, %(team_id)s, 0, %(version)s, now(), 0, 0 VALUES
"""

INSERT_PERSON_SQL = """
INSERT INTO person (id, created_at, team_id, properties, is_identified, _timestamp, _offset, is_deleted) SELECT %(id)s, %(created_at)s, %(team_id)s, %(properties)s, %(is_identified)s, %(_timestamp)s, 0, 0
"""
