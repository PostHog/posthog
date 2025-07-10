from typing import Any, Literal, TypedDict
from uuid import uuid4
import hashlib
import time

from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI

import structlog


from ee.hogai.utils.types import AssistantState, PartialAssistantState
from posthog.schema import AssistantToolCallMessage
from ee.hogai.graph.base import AssistantNode
from .prompts import SINGLE_PASS_INSIGHT_SELECTION_PROMPT

from posthog.models import InsightViewed


class RawInsightData(TypedDict, total=False):
    """Raw insight data from database query."""

    insight_id: int
    insight__name: str | None
    insight__description: str | None
    insight__derived_name: str | None
    insight__query: dict[str, Any] | None  # Full query data
    insight__short_id: str | None  # Short ID for URLs
    keyword_score: float  # Added during processing
    semantic_score: float  # Added during processing
    relevance_score: float  # Added during processing


class InsightWithScores(TypedDict):
    """Insight data with relevance scoring."""

    insight_id: int
    insight__name: str | None
    insight__description: str | None
    insight__derived_name: str | None
    insight__query: dict[str, Any] | None
    insight__short_id: str | None
    keyword_score: float
    semantic_score: float
    relevance_score: float


class EnrichedInsight(TypedDict):
    """Full insight data with query information."""

    id: int
    name: str | None
    derived_name: str | None
    description: str | None
    query: dict[str, Any]
    short_id: str
    relevance_score: float


class CacheStats(TypedDict):
    """Cache performance statistics."""

    hits: int
    misses: int


class BestInsightSelection(TypedDict):
    """Structured output from LLM for selecting the single best insight."""

    selected_insight: str
    confidence: float
    reasoning: str


class InsightSearchNode(AssistantNode):
    logger = structlog.get_logger(__name__)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # In-memory cache for semantic filtering results (TTL: 5 minutes)
        self._semantic_cache = {}
        self._cache_ttl = 300  # 5 minutes
        # Cache tracking variables
        self._current_cache_hits = 0
        self._current_cache_misses = 0

    def _get_cache_key(self, query: str, insight_names: list[str]) -> str:
        """Generate cache key for semantic filtering results."""
        # Use query + insight count + hash of names for better cache hit rates
        # This allows cache hits when insight sets have similar composition
        cleaned_names = [name for name in insight_names if name is not None]
        names_hash = hashlib.md5(",".join(sorted(cleaned_names)).encode()).hexdigest()[:8]
        content = f"{query}::{len(cleaned_names)}::{names_hash}"
        return hashlib.md5(content.encode()).hexdigest()

    def _get_cached_semantic_result(self, cache_key: str) -> tuple[BestInsightSelection | None, bool]:
        """
        Retrieve cached LLM semantic filtering results to avoid redundant API calls.

        This cache is essential for performance because:
        - LLM API calls cost money and have rate limits
        - Each call takes 200-500ms (or even more!) vs ~1ms for cache hits
        - Users often make similar/incremental searches within minutes

        Args:
            cache_key: MD5 hash of query + insight names combination, this should be enough

        Returns:
            tuple: (cached_data, was_cache_hit)
                - cached_data: dict with LLM ratings if valid, None if cache miss
                - was_cache_hit: bool indicating if cache was hit or missed

        Side effects:
            Automatically removes expired cache entries to prevent memory bloat (keep last 100 entries)
        """
        if cache_key in self._semantic_cache:
            cached_data, timestamp = self._semantic_cache[cache_key]
            if time.time() - timestamp < self._cache_ttl:
                return cached_data, True
            else:
                del self._semantic_cache[cache_key]
        return None, False

    def _cache_semantic_result(self, cache_key: str, result: BestInsightSelection) -> None:
        """Cache semantic filtering result with timestamp."""
        # Simple cache management - keep last 100 entries
        if len(self._semantic_cache) > 100:
            # Remove oldest entries (basic LRU)
            oldest_key = min(self._semantic_cache.keys(), key=lambda k: self._semantic_cache[k][1])
            del self._semantic_cache[oldest_key]

        self._semantic_cache[cache_key] = (result, time.time())

    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        start_time = time.time()
        search_query = state.search_insights_query
        conversation_id = config["configurable"]["thread_id"]

        cache_hits = 0
        cache_misses = 0

        try:
            results, cache_stats = self._search_insights(search_insights_query=search_query)
            cache_hits = cache_stats.get("hits", 0)
            cache_misses = cache_stats.get("misses", 0)

            # Format the results for display
            formatted_content = self._format_insight_results(results, search_query)

            # Log performance metrics
            execution_time = time.time() - start_time
            total_cache_attempts = cache_hits + cache_misses
            cache_hit_rate = round(cache_hits / max(total_cache_attempts, 1), 2) if total_cache_attempts > 0 else 0

            self.logger.info(
                f"Insight search completed",
                extra={
                    "team_id": self._team.id,
                    "conversation_id": conversation_id,
                    "query_length": len(search_query) if search_query else 0,
                    "results_count": len(results),
                    "execution_time_ms": round(execution_time * 1000, 2),
                    "used_semantic_filtering": bool(search_query),
                    "cache_hit_rate": cache_hit_rate,
                    "cache_hits": cache_hits,
                    "cache_misses": cache_misses,
                },
            )

            return PartialAssistantState(
                messages=[
                    AssistantToolCallMessage(
                        content=formatted_content,
                        tool_call_id=state.root_tool_call_id,
                        id=str(uuid4()),
                    ),
                ],
                # Reset state values
                search_insights_query=None,
                root_tool_call_id=None,
            )

        except Exception as e:
            execution_time = time.time() - start_time
            total_cache_attempts = cache_hits + cache_misses
            cache_hit_rate = round(cache_hits / max(total_cache_attempts, 1), 2) if total_cache_attempts > 0 else 0

            self.logger.exception(
                f"Insight search failed",
                extra={
                    "team_id": self._team.id,
                    "conversation_id": conversation_id,
                    "query_length": len(search_query) if search_query else 0,
                    "execution_time_ms": round(execution_time * 1000, 2),
                    "cache_hit_rate": cache_hit_rate,
                    "cache_hits": cache_hits,
                    "cache_misses": cache_misses,
                    "error": str(e),
                },
            )

            return PartialAssistantState(
                messages=[
                    AssistantToolCallMessage(
                        content="INSTRUCTIONS: Tell the user that you encountered an issue while searching for insights and suggest they try again with a different search term.",
                        tool_call_id=state.root_tool_call_id or "unknown",
                        id=str(uuid4()),
                    ),
                ],
                search_insights_query=None,
                root_tool_call_id=None,
            )

    def _search_insights(
        self, search_insights_query: str | None = None, limit: int = 10
    ) -> tuple[list[EnrichedInsight], CacheStats]:
        """Optimized insight search with improved data pipeline and cache tracking."""

        # Step 1: Get basic insight data with optimized query size
        initial_fetch_size = 300 if search_insights_query else 3

        insights_qs = (
            InsightViewed.objects.filter(team__project_id=self._team.project_id)
            .select_related(
                "insight__name",
                "insight__description",
                "insight__derived_name",
                "insight__team",
                "insight__short_id",
                "insight__query",
            )
            .order_by("insight_id", "-last_viewed_at")
            .distinct("insight_id")
        )

        # Get all needed data in single query to avoid second DB call
        raw_results = list(
            insights_qs[:initial_fetch_size].values(
                "insight_id",
                "insight__name",
                "insight__description",
                "insight__derived_name",
                "insight__query",  # Full query data
                "insight__short_id",  # Short ID for URLs
            )
        )

        if not raw_results:
            cache_stats: CacheStats = {"hits": self._current_cache_hits, "misses": self._current_cache_misses}
            return [], cache_stats

        # Step 2: Apply semantic filtering if query exists
        if search_insights_query:
            filtered_results = self._apply_semantic_filtering(raw_results, search_insights_query)

            if filtered_results:
                # Step 3: Convert to enriched insights (no additional DB call needed)
                enriched_results = self._convert_to_enriched_insights(filtered_results)

                if enriched_results:
                    # Step 4: Return highest scoring insight (already sorted by relevance)
                    results = enriched_results[:1]
                    cache_stats: CacheStats = {"hits": self._current_cache_hits, "misses": self._current_cache_misses}
                    return results, cache_stats

        # Fallback: convert most recent insight without semantic filtering
        fallback_insights: list[InsightWithScores] = [
            {
                "insight_id": result["insight_id"],
                "insight__name": result["insight__name"],
                "insight__description": result["insight__description"],
                "insight__derived_name": result["insight__derived_name"],
                "insight__query": result["insight__query"],
                "insight__short_id": result["insight__short_id"],
                "keyword_score": 0.0,
                "semantic_score": 0.5,
                "relevance_score": 0.5,
            }
            for result in raw_results[:1]  # Just get the most recent one
        ]

        results = self._convert_to_enriched_insights(fallback_insights)

        # Return results and cache stats
        cache_stats: CacheStats = {"hits": self._current_cache_hits, "misses": self._current_cache_misses}
        return results, cache_stats

    def router(self, state: AssistantState) -> Literal["end", "root"]:
        return "root"

    def _semantic_filter_insights(self, insights: list[RawInsightData], query: str | None) -> list[InsightWithScores]:
        """Filter insights by semantic relevance using LLM classification."""
        if not query or not insights:
            # Convert to InsightWithScores with default scores
            return [
                {
                    "insight_id": insight["insight_id"],
                    "insight__name": insight["insight__name"],
                    "insight__description": insight["insight__description"],
                    "insight__derived_name": insight["insight__derived_name"],
                    "insight__query": insight["insight__query"],
                    "insight__short_id": insight["insight__short_id"],
                    "keyword_score": 0.0,
                    "semantic_score": 0.5,
                    "relevance_score": 0.5,
                }
                for insight in insights
            ]

        # Apply semantic filtering with structured output (returns filtered results)
        return self._apply_semantic_filtering(insights, query)

    def _convert_to_enriched_insights(self, insights_with_scores: list[InsightWithScores]) -> list[EnrichedInsight]:
        """Convert InsightWithScores to EnrichedInsight format (no additional DB calls needed)."""
        enriched_insights = []

        for insight in insights_with_scores:
            enriched_insights.append(
                {
                    "id": insight["insight_id"],
                    "name": insight["insight__name"],
                    "derived_name": insight["insight__derived_name"],
                    "description": insight["insight__description"],
                    "query": insight["insight__query"] or {},
                    "short_id": insight["insight__short_id"] or "",
                    "relevance_score": insight["relevance_score"],
                }
            )

        return enriched_insights

    def _apply_semantic_filtering(self, insights: list[RawInsightData], query: str) -> list[InsightWithScores]:
        """Apply LLM-based semantic filtering to select the single best insight."""
        MAX_INSIGHTS_PER_BATCH = 50
        limited_insights = insights[:MAX_INSIGHTS_PER_BATCH]

        # Create insight names mapping for easier lookup
        insight_by_name = {}
        insights_text = ""

        for insight in limited_insights:
            name = insight.get("insight__name") or insight.get("insight__derived_name", "Unnamed")
            description = insight.get("insight__description")

            # Store insight by name for later lookup
            insight_by_name[name] = insight

            # Format insight for LLM
            if description:
                insights_text += f"📊 {name} - {description}\n"
            else:
                insights_text += f"📊 {name}\n"

        # Check cache first
        cache_key = self._get_cache_key(query, list(insight_by_name.keys()))
        cached_selection, was_cache_hit = self._get_cached_semantic_result(cache_key)

        if was_cache_hit:
            self._current_cache_hits += 1
            selection_result = cached_selection
        else:
            self._current_cache_misses += 1
            # Use structured output for reliable parsing
            formatted_prompt = SINGLE_PASS_INSIGHT_SELECTION_PROMPT.format(
                query=query, insights_list=insights_text.strip()
            )

            structured_model = self._model.with_structured_output(BestInsightSelection)

            try:
                selection_result = structured_model.invoke(formatted_prompt)

                # Cache the structured results
                self._cache_semantic_result(cache_key, selection_result)

            except Exception as e:
                self.logger.warning(f"Structured semantic filtering failed: {e}, falling back to most recent insight")
                # Fast fallback: return the most recent insight
                return [
                    {
                        "insight_id": limited_insights[0]["insight_id"],
                        "insight__name": limited_insights[0]["insight__name"],
                        "insight__description": limited_insights[0]["insight__description"],
                        "insight__derived_name": limited_insights[0].get("insight__derived_name"),
                        "insight__query": limited_insights[0].get("insight__query"),
                        "insight__short_id": limited_insights[0].get("insight__short_id"),
                        "keyword_score": 0.0,
                        "semantic_score": 0.3,
                        "relevance_score": 0.3,
                    }
                ]

        # Convert the selected insight to InsightWithScores format
        selected_insight_name = selection_result.get("selected_insight", "")
        confidence = selection_result.get("confidence", 0.7)
        if selected_insight_name in insight_by_name:
            insight = insight_by_name[selected_insight_name]
            return [
                {
                    "insight_id": insight["insight_id"],
                    "insight__name": insight["insight__name"],
                    "insight__description": insight["insight__description"],
                    "insight__derived_name": insight.get("insight__derived_name"),
                    "insight__query": insight.get("insight__query"),
                    "insight__short_id": insight.get("insight__short_id"),
                    "keyword_score": 0.0,
                    "semantic_score": confidence,
                    "relevance_score": confidence,
                }
            ]
        else:
            # Fallback to most recent if selected insight not found
            return [
                {
                    "insight_id": limited_insights[0]["insight_id"],
                    "insight__name": limited_insights[0]["insight__name"],
                    "insight__description": limited_insights[0]["insight__description"],
                    "insight__derived_name": limited_insights[0].get("insight__derived_name"),
                    "insight__query": limited_insights[0].get("insight__query"),
                    "insight__short_id": limited_insights[0].get("insight__short_id"),
                    "keyword_score": 0.0,
                    "semantic_score": 0.3,
                    "relevance_score": 0.3,
                }
            ]

    def _summarize_query_data(self, query_data: dict[str, Any]) -> str:
        """Summarize query data for LLM readability."""
        if query_data:
            query_kind = query_data.get("kind", "Unknown")
            if "source" in query_data:
                source_kind = query_data["source"].get("kind", "Unknown")
                return f"{source_kind} analysis ({query_kind})"
            return f"{query_kind} analysis"
        else:
            return "No query data available"

    def _format_insight_results(self, results: list[EnrichedInsight], search_query: str | None) -> str:
        """Format insight search results for tool call message to Root node."""

        if not results:
            return f"No insights found matching '{search_query or 'your search'}'.\n\nSuggest that the user try:\n- Using different keywords\n- Searching for broader terms\n- Creating a new insight instead"

        header = f"Found {len(results)} insight{'s' if len(results) != 1 else ''}"
        if search_query:
            header += f" matching '{search_query}'"
        header += ":\n\n"

        formatted_results = []
        for i, insight in enumerate(results, 1):
            name = insight.get("name") or insight.get("derived_name", "Unnamed Insight")
            description = insight.get("description")
            insight_short_id = insight.get("short_id")
            insight_url = f"/insights/{insight_short_id}"

            if description:
                result_block = f"""**{i}. {name}**
Description: {description}
[View Insight →]({insight_url})"""
            else:
                result_block = f"""**{i}. {name}**
[View Insight →]({insight_url})"""

            if query_data := insight.get("query", {}):
                query_summary = self._summarize_query_data(query_data)
                result_block += f"\nType: {query_summary}"

            formatted_results.append(result_block)

        content = header + "\n\n".join(formatted_results)

        if len(results) == 1:
            content += "\n\nINSTRUCTIONS: Ask the user if they want to modify this insight or use it as a starting point for a new one."
        else:
            content += "\n\nINSTRUCTIONS: Ask the user if they want to modify one of these insights, or use them as a starting point for a new one."

        return content

    @property
    def _model(self):
        return ChatOpenAI(model="gpt-4.1-mini", temperature=0.7, max_completion_tokens=1000)
