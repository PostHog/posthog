from ee.hogai.taxonomy_agent.toolkit import TaxonomyAgentToolkit, ToolkitTool


class SQLTaxonomyAgentToolkit(TaxonomyAgentToolkit):
    def _get_tools(self) -> list[ToolkitTool]:
        return [
            *self._default_tools,
            {
                "name": "final_answer",
                "signature": "(final_response: str)",
                "description": """
                    Use this tool to provide the final answer to the user's question.

                    Answer in the following format:
                    ```
                    Events:
                    - event 1
                        - how it will be used
                        - conditions
                    - event 2
                        - how it will be used
                        - conditions
                    - repeat for each event...

                    Aggregation logic:
                    ...
                    ```

                    Args:
                        final_response: List all events and properties that you want to use to answer the question.
                """,
            },
        ]


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
