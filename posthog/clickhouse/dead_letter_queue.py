# We pipe our Kafka dead letter queue into CH for easier analysis and longer retention
# This allows us to explore errors and replay events with ease

DEAD_LETTER_QUEUE_TABLE = "events_dead_letter_queue"


INSERT_DEAD_LETTER_QUEUE_EVENT_SQL = """
INSERT INTO events_dead_letter_queue
SELECT
%(id)s,
%(event_uuid)s,
%(event)s,
%(properties)s,
%(distinct_id)s,
%(team_id)s,
%(elements_chain)s,
%(created_at)s,
%(ip)s,
%(site_url)s,
%(now)s,
%(raw_payload)s,
%(error_timestamp)s,
%(error_location)s,
%(error)s,
['some_tag'],
0,
now()
"""
