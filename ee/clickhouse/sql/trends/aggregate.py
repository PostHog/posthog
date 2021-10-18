AGGREGATE_SQL = """
SELECT groupArray(day_start) as date, groupArray(count) as data FROM (
    SELECT {smoothing_operation} AS count, day_start 
    from (
        {null_sql} 
        UNION ALL 
        {content_sql}
    ) 
    group by day_start 
    order by day_start
    SETTINGS allow_experimental_window_functions = 1
)
"""
