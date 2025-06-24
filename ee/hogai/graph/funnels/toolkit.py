from ..taxonomy_agent.toolkit import TaxonomyAgentToolkit, ToolkitTool
from ee.hogai.utils.helpers import dereference_schema
from posthog.schema import AssistantFunnelsQuery


class FunnelsTaxonomyAgentToolkit(TaxonomyAgentToolkit):
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
                    Sequence:
                    1. event: event name 1
                        - property filter 1:
                            - entity
                            - property name
                            - property type
                            - operator
                            - property value
                        - property filter 2... Repeat for each property filter.
                    2. action: action name 2
                        - action id: `numeric id`
                        - property filter 1:
                            - entity
                            - property name
                            - property type
                            - operator
                            - property value
                        - property filter 2... Repeat for each property filter.
                    3. Repeat for each event or action...

                    (if exclusion steps are used)
                    Exclusions:
                    - exclusion event name 1
                        - start index: 1
                        - end index: 2
                    - exclusion event name 2... Repeat for each exclusion...

                    (if a breakdown is used)
                    Breakdown by:
                    - entity
                    - property name

                    (if a time period is explicitly mentioned)
                    Time period: from and/or to dates or durations. For example: `last 1 week`, `last 12 days`, `from 2025-01-15 to 2025-01-20`, `2025-01-15`, from `last month` to `2024-11-15`.
                    ```

                    Args:
                        final_response: List all events, actions, and properties that you want to use to answer the question.
                """,
            },
        ]


def generate_funnel_schema() -> dict:
    schema = AssistantFunnelsQuery.model_json_schema()
    return {
        "name": "output_insight_schema",
        "description": "Outputs the JSON schema of a product analytics insight",
        "parameters": {
            "type": "object",
            "properties": {
                "query": dereference_schema(schema),
            },
            "additionalProperties": False,
            "required": ["query"],
        },
    }


FUNNEL_SCHEMA = generate_funnel_schema()
