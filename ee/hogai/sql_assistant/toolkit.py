from ee.hogai.taxonomy_agent.toolkit import TaxonomyAgentToolkit, ToolkitTool


class SQLAssistantToolkit(TaxonomyAgentToolkit):
    def _get_tools(self) -> list[ToolkitTool]:
        return [
            {
                "name": "generate_hogql_query",
                "signature": "()",
                "description": """
                    Use this tool to generate a hogQL query to answer the user's question.
                """,
            },
        ]
