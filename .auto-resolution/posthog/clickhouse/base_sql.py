COPY_ROWS_BETWEEN_TEAMS_BASE_SQL = """
    INSERT INTO {table_name} (team_id, {columns_except_team_id}) SELECT %(target_team_id)s, {columns_except_team_id}
    FROM {table_name} WHERE team_id = %(source_team_id)s
"""
