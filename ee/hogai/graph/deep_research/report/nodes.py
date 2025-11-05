from uuid import uuid4

from langchain_core.messages import ToolMessage as LangchainToolMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel

from posthog.schema import (
    AssistantFunnelsQuery,
    AssistantHogQLQuery,
    AssistantRetentionQuery,
    AssistantToolCallMessage,
    AssistantTrendsQuery,
    DeepResearchNotebook,
    DeepResearchType,
    NotebookUpdateMessage,
)

from posthog.exceptions_capture import capture_exception

from ee.hogai.graph.deep_research.base.nodes import DeepResearchNode
from ee.hogai.graph.deep_research.report.prompts import DEEP_RESEARCH_REPORT_PROMPT, FINAL_REPORT_USER_PROMPT
from ee.hogai.graph.deep_research.types import (
    DeepResearchIntermediateResult,
    DeepResearchNodeName,
    DeepResearchState,
    PartialDeepResearchState,
)
from ee.hogai.graph.query_executor.query_executor import AssistantQueryExecutor
from ee.hogai.notebook.notebook_serializer import NotebookContext
from ee.hogai.utils.types.base import InsightArtifact, TaskArtifact
from ee.hogai.utils.types.composed import MaxNodeName


class FormattedInsight(BaseModel):
    """Represents a formatted insight for the report."""

    id: str
    description: str
    formatted_results: str
    query_type: str


class DeepResearchReportNode(DeepResearchNode):
    """
    Final node in the deep research graph that generates a comprehensive report.

    This node:
    1. Collects all intermediate results from the research process
    2. Formats insight artifacts using the query executor
    3. Generates a final markdown report with embedded insight references
    """

    @property
    def node_name(self) -> MaxNodeName:
        return DeepResearchNodeName.REPORT

    async def arun(self, state: DeepResearchState, config: RunnableConfig) -> PartialDeepResearchState:
        # Collect all artifacts from task results
        all_artifacts = self._collect_all_artifacts(state)

        # Format insights for the report
        formatted_insights = self._format_insights(all_artifacts)

        # Prepare intermediate results for the prompt
        intermediate_results_text = self._format_intermediate_results(state.intermediate_results)

        # Prepare artifacts summary for the prompt
        artifacts_text = self._format_artifacts_summary(formatted_insights)

        # Generate the report using the LLM
        instructions = DEEP_RESEARCH_REPORT_PROMPT

        model = self._get_model(instructions, state.previous_response_id)

        last_message = state.messages[-1]
        if not isinstance(last_message, AssistantToolCallMessage):
            raise ValueError("Last message is not a tool call message.")

        messages: list[tuple[str, str] | LangchainToolMessage] = [
            LangchainToolMessage(content=last_message.content, tool_call_id=last_message.tool_call_id),
            ("human", FINAL_REPORT_USER_PROMPT),
        ]

        prompt = ChatPromptTemplate.from_messages(messages, template_format="mustache")

        chain = prompt | model

        context = self._create_context(all_artifacts)

        notebook = await self._astream_notebook(
            chain,
            config,
            stream_parameters={
                "intermediate_results": intermediate_results_text,
                "artifacts": artifacts_text,
            },
            context=context,
        )

        notebook_title = notebook.title if notebook else "Research Report"
        current_notebook_info = DeepResearchNotebook(
            notebook_type=DeepResearchType.REPORT,
            notebook_id=notebook.short_id,
            title=notebook_title,
        )

        # Update current run notebooks with the report
        current_run_notebooks = (state.current_run_notebooks or []) + [current_notebook_info]

        # Combine all conversation notebooks with the current report for the final display
        all_conversation_notebooks = [*state.conversation_notebooks, current_notebook_info]

        notebook_update_message = NotebookUpdateMessage(
            id=str(uuid4()),
            notebook_id=notebook.short_id,
            content=notebook.content,
            notebook_type="deep_research",
            conversation_notebooks=all_conversation_notebooks,
            current_run_notebooks=current_run_notebooks,
        )

        self.dispatcher.message(notebook_update_message)

        return PartialDeepResearchState(
            messages=[notebook_update_message],
            conversation_notebooks=[current_notebook_info],
            current_run_notebooks=current_run_notebooks,
        )

    def _collect_all_artifacts(self, state: DeepResearchState) -> list[TaskArtifact]:
        """Collect all artifacts from task results."""
        artifacts: list[TaskArtifact] = []
        for result in state.task_results:
            artifacts.extend(result.artifacts)

        valid_ids = set()
        for intermediate_result in state.intermediate_results:
            valid_ids.update(intermediate_result.artifact_ids)

        artifacts = [artifact for artifact in artifacts if artifact.task_id in valid_ids]
        return artifacts

    def _format_insights(self, artifacts: list[TaskArtifact]) -> list[FormattedInsight]:
        """Format insight artifacts using the query executor."""
        formatted_insights = []

        for artifact in artifacts:
            if not isinstance(artifact, InsightArtifact) or artifact.query is None:
                # Skip artifacts without queries (shouldn't happen in production)
                continue

            try:
                executor = AssistantQueryExecutor(self._team, self._utc_now_datetime)
                # Execute and format the query
                formatted_results, _ = executor.run_and_format_query(artifact.query)

                # Determine query type for context
                query_type = self._get_query_type_name(artifact.query)

                formatted_insights.append(
                    FormattedInsight(
                        id=artifact.task_id,
                        description=artifact.content,
                        formatted_results=formatted_results,
                        query_type=query_type,
                    )
                )
            except Exception as e:
                # skip problematic insights
                capture_exception(e)
                formatted_insights.append(  # TODO: remove me
                    FormattedInsight(
                        id=artifact.task_id,
                        description=artifact.content,
                        formatted_results="",
                        query_type=self._get_query_type_name(artifact.query),
                    )
                )
                continue

        return formatted_insights

    def _get_query_type_name(self, query) -> str:
        """Get a human-readable name for the query type."""
        if isinstance(query, AssistantTrendsQuery):
            return "Trends"
        elif isinstance(query, AssistantFunnelsQuery):
            return "Funnel"
        elif isinstance(query, AssistantRetentionQuery):
            return "Retention"
        elif isinstance(query, AssistantHogQLQuery):
            return "SQL Query"
        else:
            return "Query"

    def _format_intermediate_results(self, intermediate_results: list[DeepResearchIntermediateResult]) -> str:
        """Format intermediate results for inclusion in the prompt."""
        if not intermediate_results:
            return "No intermediate results available."

        formatted_parts = []
        for i, result in enumerate(intermediate_results, 1):
            formatted_parts.append(f"### Intermediate Result {i}")
            formatted_parts.append(result.content)
            if result.artifact_ids:
                formatted_parts.append(f"Referenced insights: {', '.join(result.artifact_ids)}")
            formatted_parts.append("")  # Empty line for spacing

        return "\n".join(formatted_parts)

    def _format_artifacts_summary(self, formatted_insights: list[FormattedInsight]) -> str:
        """Format artifacts summary for inclusion in the prompt."""
        if not formatted_insights:
            return "No insights available."

        formatted_parts = []
        for insight in formatted_insights:
            formatted_parts.append(f"### Insight: {insight.id}")
            formatted_parts.append(f"**Type**: {insight.query_type}")
            formatted_parts.append(f"**Description**: {insight.description}")
            formatted_parts.append("**Data**:")
            formatted_parts.append(insight.formatted_results)
            formatted_parts.append("")  # Empty line for spacing

        return "\n".join(formatted_parts)

    def _create_context(self, artifacts: list[TaskArtifact]) -> NotebookContext:
        """
        Create a context for the notebook serializer.
        """
        context = NotebookContext(
            insights={artifact.task_id: artifact for artifact in artifacts if isinstance(artifact, InsightArtifact)}
        )
        return context
