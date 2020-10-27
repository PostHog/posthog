AVERAGE_SQL = """
    SELECT 
        SUM(total), 
        day_start 
    FROM 
        ({null_sql} UNION ALL {sessions}) 
    GROUP BY 
        day_start 
    ORDER BY 
        day_start
"""
