AGGREGATE_SQL = """
SELECT groupArray(day_start), groupArray(count) FROM (
    SELECT SUM(total) AS count, day_start from ({null_sql} UNION ALL {content_sql}) group by day_start order by day_start
)
"""
