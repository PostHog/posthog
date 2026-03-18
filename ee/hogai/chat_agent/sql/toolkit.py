def generate_sql_schema() -> dict:
    return {
        "name": "output_insight_schema",
        "description": "Outputs the final SQL query",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The SQL query to be executed",
                },
            },
            "additionalProperties": False,
            "required": ["query"],
        },
    }


SQL_SCHEMA = generate_sql_schema()
