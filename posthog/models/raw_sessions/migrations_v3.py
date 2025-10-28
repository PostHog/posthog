DROP_PERSON_ID = """
ALTER TABLE {table_name}
DROP COLUMN IF EXISTS person_id
"""


ADD_HAS_REPLAY_EVENTS = """
ALTER TABLE {table_name}
ADD COLUMN IF NOT EXISTS has_replay_events SimpleAggregateFunction(max, Boolean) AFTER flag_values;
"""
