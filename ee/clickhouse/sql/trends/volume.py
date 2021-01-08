VOLUME_SQL = """
SELECT {aggregate_operation} as total, toDateTime({interval}({timestamp}), 'UTC') as day_start from events {event_join} where team_id = {team_id} and event = %(event)s {filters} AND {interval}(timestamp) >= {interval}(toDateTime(%(date_from)s)) AND timestamp <= %(date_to)s GROUP BY {interval}({timestamp})
"""

VOLUME_ACTIONS_SQL = """
SELECT {aggregate_operation} as total, toDateTime({interval}({timestamp}), 'UTC') as day_start from events {event_join} where team_id = {team_id} and {actions_query} {filters} AND {interval}(timestamp) >= {interval}(toDateTime(%(date_from)s)) AND timestamp <= %(date_to)s GROUP BY {interval}({timestamp})
"""

VOLUME_TOTAL_AGGREGATE_SQL = """
SELECT {aggregate_operation} as total from events {event_join} where team_id = {team_id} and event = %(event)s {filters} AND {interval}(timestamp) >= {interval}(toDateTime(%(date_from)s)) AND timestamp <= %(date_to)s
"""

VOLUME__TOTAL_AGGREGATE_ACTIONS_SQL = """
SELECT {aggregate_operation} as total from events {event_join} where team_id = {team_id} and {actions_query} {filters} AND {interval}(timestamp) >= {interval}(toDateTime(%(date_from)s)) AND timestamp <= %(date_to)s
"""
