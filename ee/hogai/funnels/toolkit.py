from ee.hogai.taxonomy_agent.toolkit import TaxonomyAgentToolkit, ToolkitTool


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
                    1. event 1
                        - property filter 1:
                            - entity
                            - property name
                            - property type
                            - operator
                            - property value
                        - property filter 2... Repeat for each property filter.
                    2. event 2
                        - property filter 1:
                            - entity
                            - property name
                            - property type
                            - operator
                            - property value
                        - property filter 2... Repeat for each property filter.
                    3. Repeat for each event...

                    (if exclusion steps are used)
                    Exclusions:
                    - exclusion 1
                        - start index: 1
                        - end index: 2
                    - exclusion 2... Repeat for each exclusion...

                    (if a breakdown is used)
                    Breakdown by:
                    - entity
                    - property name
                    ```

                    Args:
                        final_response: List all events and properties that you want to use to answer the question.
                """,
            },
        ]
