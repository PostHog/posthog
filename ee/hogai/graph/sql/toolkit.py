from pydantic import BaseModel, Field

from ..taxonomy_agent.toolkit import TaxonomyAgentToolkit


class final_answer(BaseModel):
    """
    Use this tool to provide the final answer to the user's question.

    Answer in the following format:
    ```
    Logic:
    - description of each logical layer of the query (if aggregations needed, include which concrete aggregation to use)


    Sources:
    - event 1
        - how it will be used, most importantly conditions
    - action ID 2
        - how it will be used, most importantly conditions
    - data warehouse table 3
        - how it will be used, most importantly conditions
    - repeat for each event/action/data warehouse table...
    ```
    """

    final_response: str = Field(
        description="List all events and properties that you want to use to answer the question."
    )


class SQLTaxonomyAgentToolkit(TaxonomyAgentToolkit):
    def _get_tools(self) -> list[BaseModel]:
        return [*self._default_tools, final_answer]


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
