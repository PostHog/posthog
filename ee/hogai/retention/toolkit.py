from ee.hogai.taxonomy_agent.toolkit import TaxonomyAgentToolkit, ToolkitTool
from ee.hogai.utils.helpers import dereference_schema
from posthog.schema import AssistantRetentionQuery


class RetentionTaxonomyAgentToolkit(TaxonomyAgentToolkit):
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
Activation event:
some event
    - property filter 1:
        - entity
        - property name
        - property type
        - operator
        - property value
    - property filter 2... Repeat for each property filter.

Retention event:
some event (can be the same as activation event, or different)
    - property filter 1:
        - entity
        - property name
        - property type
        - operator
        - property value
    - property filter 2... Repeat for each property filter.

(if filters are used)
Filters:
    - property filter 1:
        - entity
        - property name
        - property type
        - operator
        - property value
    - property filter 2... Repeat for each property filter.
```

Args:
    final_response: List all events and properties that you want to use to answer the question.""",
            },
        ]


def generate_retention_schema() -> dict:
    schema = AssistantRetentionQuery.model_json_schema()
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


RETENTION_SCHEMA = generate_retention_schema()
