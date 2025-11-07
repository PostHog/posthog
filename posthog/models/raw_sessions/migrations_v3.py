DROP_PERSON_ID = """
ALTER TABLE {table_name}
DROP COLUMN IF EXISTS person_id
"""


ADD_HAS_REPLAY_EVENTS = """
ALTER TABLE {table_name}
ADD COLUMN IF NOT EXISTS has_replay_events SimpleAggregateFunction(max, Boolean) AFTER flag_values;
"""

SPLIT_BOUNCE_RATE = """
ALTER TABLE {table_name}
DROP COLUMN IF EXISTS page_screen_autocapture_uniq_up_to,
ADD COLUMN IF NOT EXISTS page_screen_uniq_up_to AggregateFunction(uniqUpTo(1), Nullable(UUID)) AFTER screen_uniq,
ADD COLUMN IF NOT EXISTS has_autocapture SimpleAggregateFunction(max, Boolean) AFTER page_screen_uniq_up_to
;

"""
