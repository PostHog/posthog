AVERAGE_PER_PERIOD_SQL = """
    SELECT 
        AVG(session_duration_seconds) as total, 
        {interval}(timestamp) as day_start 
    FROM 
        ({sessions}) 
    GROUP BY 
        {interval}(timestamp)
"""
