GET_EARLIEST_TIMESTAMP_SQL = """
SELECT timestamp from events WHERE team_id = %(team_id)s AND timestamp > %(earliest_timestamp)s order by timestamp limit 1
"""
