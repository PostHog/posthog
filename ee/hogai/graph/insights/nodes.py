from typing import Literal
from uuid import uuid4

from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI

import structlog


from ee.hogai.utils.types import AssistantState, PartialAssistantState
from posthog.schema import (
    AssistantMessage,
)
from ee.hogai.graph.base import AssistantNode

from posthog.models import InsightViewed, Insight


class InsightSearchNode(AssistantNode):
    logger = structlog.get_logger(__name__)

    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        conversation = self._get_conversation(config["configurable"]["thread_id"])  # noqa: F841

        self.logger.info(f"The team is: {self._team} | {self._user}")
        self.logger.info(f"The search query is: {state.root_to_search_insights}")

        # perform a django query to get the insights
        results = self._search_insights(root_to_search_insights=state.root_to_search_insights)

        self.logger.info(f"The results are: {results}")

        # Format the results for display
        formatted_content = self._format_insight_results(results, state.root_to_search_insights)

        return PartialAssistantState(
            messages=[
                AssistantMessage(
                    content=formatted_content,
                    id=str(uuid4()),
                )
            ],
            # Reset state values (important for state management)
            root_to_search_insights="",
        )

    def _search_insights(self, root_to_search_insights: str | None = None, limit: int = 10):
        """Search for all insights (id, name, desc, query)"""

        # Step 1: Get basic insight data from InsightViewed
        insights_qs = InsightViewed.objects.filter(team=self._team)

        # Group by insight_id to avoid duplicates, get most recent view per insight
        insights_qs = insights_qs.order_by("insight_id", "-last_viewed_at").distinct("insight_id")

        raw_results = list(insights_qs[: limit * 5].values("insight_id", "insight__name", "insight__description"))

        # Always get full insight data for better display
        if raw_results:
            # For raw results, we need to get the full insight data too
            raw_with_full_data = []
            for result in raw_results[:5]:  # Limit to 5 for performance
                raw_with_full_data.append(
                    {
                        "insight_id": result["insight_id"],
                        "relevance_score": 0.5,  # Default score for non-semantic results
                    }
                )
            initial_enriched = self._get_full_queries_for_insights(raw_with_full_data)
        else:
            initial_enriched = []

        # Step 2: Semantic filtering with small LLM (if meaningful query)
        if self._should_semantic_filter(root_to_search_insights):
            self.logger.info(f"Running semantic filtering for query: {root_to_search_insights}")
            filtered_results = self._semantic_filter_insights(raw_results, root_to_search_insights)

            # Step 3: Get full query data for filtered insights
            if filtered_results:
                enriched_results = self._get_full_queries_for_insights(filtered_results)
                self.logger.info(f"The enriched results are: {enriched_results}")

                # Step 4: Final LLM selection of most relevant insight
                best_insight = self._select_best_insight(enriched_results, root_to_search_insights)
                return [best_insight] if best_insight else enriched_results[:1]

        # Fallback: return single best result from initial data
        if initial_enriched:
            return initial_enriched[:1]  # Always return just 1 result

        return []

    def router(self, state: AssistantState) -> Literal["end", "root"]:
        return "end"  # Change to "root" if you want conversation to continue

    def _should_semantic_filter(self, query: str | None) -> bool:
        """Only run semantic filtering for meaningful queries."""
        if not query:
            return False
        return len(query.strip()) > 3 and not query.strip().isdigit()

    def _semantic_filter_insights(self, insights: list, query: str | None) -> list:
        """Filter insights by semantic relevance using LLM classification."""
        if not query:
            return insights

        # Prepare prompt for batch evaluation
        prompt = PromptTemplate.from_template("""
  Given a search query and insight metadata, rate the relevance:

  Search Query: "{query}"
  Insight Name: "{name}"
  Insight Description: "{description}"

  Rate the relevance (choose one):
  - high: Directly matches or strongly relates to the query
  - medium: Somewhat related or partially matches
  - low: Barely related or generic connection
  - none: No meaningful connection

  Rating:""")

        # Use small, fast model for classification
        model = ChatOpenAI(model="gpt-4.1-nano", temperature=0.1, max_completion_tokens=10)

        relevant_insights = []
        for idx, insight in enumerate(insights):
            # Create prompt for each insight
            formatted_prompt = prompt.format(
                query=query, name=insight.get("insight__name", ""), description=insight.get("insight__description", "")
            )

            self.logger.info(f"Formatted prompt {idx}: {formatted_prompt}")

            # Get relevance rating
            response = model.invoke(formatted_prompt)
            self.logger.info(f"Response {idx}: {response}")
            rating = response.content.strip().lower()

            # Filter by relevance threshold
            if rating in ["high", "medium"]:
                self.logger.info(f"***WOOOO***Adding insight {idx} to relevant insights since rating is {rating}")
                relevant_insights.append({**insight, "relevance_score": 1.0 if rating == "high" else 0.7})

        # Sort by relevance score
        return sorted(relevant_insights, key=lambda x: x["relevance_score"], reverse=True)

    def _get_full_queries_for_insights(self, filtered_insights: list) -> list:
        """Step 3: Get full query data for filtered insights."""

        # Extract insight IDs from filtered results
        insight_ids = [insight["insight_id"] for insight in filtered_insights]

        # Query for full insight data including the query field
        full_insights = Insight.objects.filter(id__in=insight_ids, team=self._team, deleted=False).values(
            "id", "name", "derived_name", "description", "query", "filters", "short_id"
        )

        # Create a mapping from insight_id to full data
        insight_map = {insight["id"]: insight for insight in full_insights}

        # Merge relevance scores with full query data
        enriched_insights = []
        for filtered_insight in filtered_insights:
            insight_id = filtered_insight["insight_id"]
            if full_data := insight_map.get(insight_id):
                enriched_insights.append({**full_data, "relevance_score": filtered_insight["relevance_score"]})

        return enriched_insights

    def _select_best_insight(self, insights: list, query: str | None) -> dict | None:
        """Step 4: Select the single most relevant insight using LLM analysis."""

        if not insights:
            return None

        if not query:
            # If no query, return highest relevance score
            return max(insights, key=lambda x: x.get("relevance_score", 0))

        if len(insights) == 1:
            return insights[0]

        # Format insights for LLM evaluation
        insights_text = ""
        for i, insight in enumerate(insights, 1):
            name = insight.get("name") or insight.get("derived_name", "Unnamed")
            description = insight.get("description", "No description")
            query_data = insight.get("query", {})
            filters_data = insight.get("filters", {})

            # Simplify query/filters for readability
            query_summary = self._summarize_query_data(query_data, filters_data)

            insights_text += f"""
{i}. "{name}"
   Description: {description}
   Query: {query_summary}
   Relevance Score: {insight.get('relevance_score', 'N/A')}
"""

        prompt = f"""You are helping a user find the most relevant PostHog insight for their search.

User Search Query: "{query}"

Available Insights:{insights_text}

Select the single most relevant insight by responding with ONLY the number (1, 2, 3, etc.) that best matches the user's search intent.

Most relevant insight number:"""

        # Use a more capable model for final selection
        model = ChatOpenAI(model="gpt-4o-mini", temperature=0.1, max_completion_tokens=5)

        try:
            response = model.invoke(prompt)
            selection = response.content.strip()

            # Parse the selection
            try:
                selected_index = int(selection) - 1  # Convert to 0-based index
                if 0 <= selected_index < len(insights):
                    self.logger.info(
                        f"LLM selected insight {selected_index + 1}: {insights[selected_index].get('name')}"
                    )
                    return insights[selected_index]
            except ValueError:
                self.logger.warning(f"Could not parse LLM selection: {selection}")

            # Fallback to highest relevance score
            return max(insights, key=lambda x: x.get("relevance_score", 0))

        except Exception as e:
            self.logger.exception(f"Error in final insight selection: {e}")
            # Fallback to highest relevance score
            return max(insights, key=lambda x: x.get("relevance_score", 0))

    def _summarize_query_data(self, query_data: dict, filters_data: dict) -> str:
        """Summarize query/filters data for LLM readability."""
        if query_data:
            query_kind = query_data.get("kind", "Unknown")
            if "source" in query_data:
                source_kind = query_data["source"].get("kind", "Unknown")
                return f"{source_kind} analysis ({query_kind})"
            return f"{query_kind} analysis"
        elif filters_data:
            insight_type = filters_data.get("insight", "Unknown")
            return f"{insight_type} analysis (legacy format)"
        else:
            return "No query data available"

    def _format_insight_results(self, results: list, search_query: str | None) -> str:
        """Format insight search results for user display."""

        if not results:
            return f"No insights found matching '{search_query or 'your search'}'.\n\nYou might want to try:\n- Using different keywords\n- Searching for broader terms\n- Creating a new insight instead"

        # Header with context
        header = f"Found {len(results)} insight{'s' if len(results) != 1 else ''}"
        if search_query:
            header += f" matching '{search_query}'"
        header += ":\n\n"

        # Format each result
        formatted_results = []
        for i, insight in enumerate(results, 1):
            name = insight.get("name") or insight.get("derived_name", "Unnamed Insight")
            description = insight.get("description", "No description available")
            # insight_id = insight.get("id") or insight.get("insight_id")
            insight_short_id = insight.get("short_id")

            # Create actionable link
            insight_url = f"/insights/{insight_short_id}"

            result_block = f"""**{i}. {name}**
Description: {description}
[View Insight →]({insight_url})"""

            # Add query type if available
            if query_data := insight.get("query", {}):
                query_summary = self._summarize_query_data(query_data, insight.get("filters", {}))
                result_block += f"\nType: {query_summary}"

            formatted_results.append(result_block)

        # Combine everything
        content = header + "\n\n".join(formatted_results)

        # Add helpful footer
        if len(results) == 1:
            content += "\n\nWould you like me to help you modify this insight or create a similar one?"
        else:
            content += "\n\nWould you like me to help you explore any of these insights further?"

        return content

    @property
    def _model(self):
        return ChatOpenAI(model="gpt-4.1-nano", temperature=0.7, max_completion_tokens=100)
