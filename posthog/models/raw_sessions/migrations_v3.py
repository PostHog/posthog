from posthog.models.raw_sessions.sessions_v3 import SESSION_V3_MAX_EMAILS_PER_SESSION, SESSION_V3_MAX_HOSTS_PER_SESSION

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


ADD_EVENT_NAMES = """
ALTER TABLE {table_name}
ADD COLUMN IF NOT EXISTS event_names SimpleAggregateFunction(groupUniqArrayArray, Array(String)) AFTER flag_values
"""


ADD_EVENT_NAMES_BLOOM_FILTER = """
ALTER TABLE {table_name}
ADD INDEX IF NOT EXISTS event_names_bloom_filter event_names TYPE bloom_filter() GRANULARITY 1
"""


ADD_FLAG_KEYS = """
ALTER TABLE {table_name}
ADD COLUMN IF NOT EXISTS flag_keys SimpleAggregateFunction(groupUniqArrayArray, Array(String)) AFTER flag_values
"""


ADD_FLAG_KEYS_BLOOM_FILTER = """
ALTER TABLE {table_name}
ADD INDEX IF NOT EXISTS flag_keys_bloom_filter flag_keys TYPE bloom_filter() GRANULARITY 1
"""


ADD_HOSTS = """
ALTER TABLE {{table_name}}
ADD COLUMN IF NOT EXISTS hosts SimpleAggregateFunction(groupUniqArrayArray({max_hosts}), Array(String)) AFTER event_names
""".format(max_hosts=SESSION_V3_MAX_HOSTS_PER_SESSION)


ADD_HOSTS_BLOOM_FILTER = """
ALTER TABLE {table_name}
ADD INDEX IF NOT EXISTS hosts_bloom_filter hosts TYPE bloom_filter() GRANULARITY 1
"""


ADD_EMAILS = """
ALTER TABLE {{table_name}}
ADD COLUMN IF NOT EXISTS emails SimpleAggregateFunction(groupUniqArrayArray({max_emails}), Array(String)) AFTER hosts
""".format(max_emails=SESSION_V3_MAX_EMAILS_PER_SESSION)


ADD_EMAILS_BLOOM_FILTER = """
ALTER TABLE {table_name}
ADD INDEX IF NOT EXISTS emails_bloom_filter emails TYPE bloom_filter() GRANULARITY 1
"""


DROP_URLS = """
ALTER TABLE {table_name}
DROP COLUMN IF EXISTS urls
"""


ADD_URLS = """
ALTER TABLE {table_name}
ADD COLUMN IF NOT EXISTS urls SimpleAggregateFunction(groupUniqArrayArray(2000), Array(String)) AFTER max_inserted_at
"""
