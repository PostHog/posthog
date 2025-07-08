from typing import Literal
from uuid import uuid4
import hashlib
import time

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

    _SEMANTIC_FILTER_PROMPT = PromptTemplate.from_template("""
Rate the relevance of each insight to the search query.

Search Query: "{query}"

Insights to rate:
{insights_list}

For each insight, respond with ONLY the number followed by relevance rating:
Format: "1: high, 2: medium, 3: low, 4: none"

Ratings:
- high: Directly matches or strongly relates to the query
- medium: Somewhat related or partially matches
- low: Barely related or generic connection
- none: No meaningful connection

Your response:""")

    _IMPROVED_SEMANTIC_FILTER_PROMPT = PromptTemplate.from_template("""
Rate the relevance of each insight to the search query. Pay special attention to exact keyword matches in insight names (marked with ⭐ EXACT MATCH).

Search Query: "{query}"

Insights to rate:
{insights_list}

For each insight, respond with ONLY the number followed by relevance rating:
Format: "1: high, 2: medium, 3: low, 4: none"

Ratings:
- high: Exact keyword match in name OR directly matches query intent
- medium: Partial keyword match OR somewhat related to query
- low: Generic connection to query topics
- none: No meaningful connection

IMPORTANT: Insights marked with ⭐ EXACT MATCH should generally be rated 'high' unless completely unrelated to the query context.

Your response:""")

    # In-memory cache for semantic filtering results (TTL: 5 minutes)
    _semantic_cache = {}
    _cache_ttl = 300  # 5 minutes

    @classmethod
    def _get_cache_key(cls, query: str, insight_names: list[str]) -> str:
        """Generate cache key for semantic filtering results."""
        # Filter out None values and convert to strings to avoid sorting errors
        cleaned_names = [name for name in insight_names if name is not None]
        content = f"{query}::{','.join(sorted(cleaned_names))}"
        return hashlib.md5(content.encode()).hexdigest()

    @classmethod
    def _get_cached_semantic_result(cls, cache_key: str) -> tuple[dict | None, bool]:
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
        if cache_key in cls._semantic_cache:
            cached_data, timestamp = cls._semantic_cache[cache_key]
            if time.time() - timestamp < cls._cache_ttl:
                return cached_data, True
            else:
                del cls._semantic_cache[cache_key]
        return None, False

    @classmethod
    def _cache_semantic_result(cls, cache_key: str, result: dict) -> None:
        """Cache semantic filtering result with timestamp."""
        # Simple cache management - keep last 100 entries
        if len(cls._semantic_cache) > 100:
            # Remove oldest entries (basic LRU)
            oldest_key = min(cls._semantic_cache.keys(), key=lambda k: cls._semantic_cache[k][1])
            del cls._semantic_cache[oldest_key]

        cls._semantic_cache[cache_key] = (result, time.time())

    def run(self, state: AssistantState, config: RunnableConfig) -> PartialAssistantState | None:
        start_time = time.time()
        search_query = state.root_to_search_insights
        conversation_id = config["configurable"]["thread_id"]

        cache_hits = 0
        cache_misses = 0

        try:
            results, cache_stats = self._search_insights_with_cache_tracking(root_to_search_insights=search_query)
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
                    "used_semantic_filtering": self._should_semantic_filter(search_query),
                    "cache_hit_rate": cache_hit_rate,
                    "cache_hits": cache_hits,
                    "cache_misses": cache_misses,
                },
            )

            return PartialAssistantState(
                messages=[
                    AssistantMessage(
                        content=formatted_content,
                        id=str(uuid4()),
                    )
                ],
                # Reset state values
                root_to_search_insights="",
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
                    AssistantMessage(
                        content="Sorry, I encountered an issue while searching for insights. Please try again with a different search term.",
                        id=str(uuid4()),
                    )
                ],
                root_to_search_insights="",
            )

    def _search_insights_with_cache_tracking(
        self, root_to_search_insights: str | None = None, limit: int = 10
    ) -> tuple[list, dict]:
        """Wrapper around _search_insights that tracks cache statistics."""
        self._current_cache_hits = 0
        self._current_cache_misses = 0

        # Perform the search
        results = self._search_insights(root_to_search_insights, limit)

        # Return results and cache stats
        cache_stats = {"hits": self._current_cache_hits, "misses": self._current_cache_misses}

        return results, cache_stats

    def _search_insights(self, root_to_search_insights: str | None = None, limit: int = 10):
        """Optimized insight search with improved data pipeline."""

        # Step 1: Get basic insight data with optimized query size
        initial_fetch_size = 1500 if self._should_semantic_filter(root_to_search_insights) else 3

        insights_qs = (
            InsightViewed.objects.filter(team=self._team)
            .select_related("insight__team", "insight__created_by")  # Optimize all joins
            .order_by("insight_id", "-last_viewed_at")
            .distinct("insight_id")
        )

        # Get basic data for semantic filtering or fallback with optimized field access
        raw_results = list(
            insights_qs[:initial_fetch_size].values(
                "insight_id",
                "insight__name",
                "insight__description",
                "insight__derived_name",  # Include derived_name for better fallback
            )
        )

        if not raw_results:
            return []

        # Step 2: Apply semantic filtering if needed
        if self._should_semantic_filter(root_to_search_insights):
            filtered_results = self._semantic_filter_insights(raw_results, root_to_search_insights)

            if filtered_results:
                # Step 3: Get full query data for filtered insights (single DB call)
                enriched_results = self._get_full_queries_for_insights(filtered_results)

                if enriched_results:
                    # Step 4: Final LLM selection of most relevant insight
                    best_insight = self._select_best_insight(enriched_results, root_to_search_insights)
                    return [best_insight] if best_insight else enriched_results[:1]

        # Fallback: get full data for most recent insights without semantic filtering
        fallback_insights = [
            {"insight_id": result["insight_id"], "relevance_score": 0.5}
            for result in raw_results[:1]  # Just get the most recent one
        ]

        enriched_fallback = self._get_full_queries_for_insights(fallback_insights)
        return enriched_fallback[:1] if enriched_fallback else []

    def router(self, state: AssistantState) -> Literal["end", "root"]:
        return "end"

    def _should_semantic_filter(self, query: str | None) -> bool:
        """Only run semantic filtering for "meaningful" queries."""
        if not query:
            return False
        return len(query.strip()) > 3 and not query.strip().isdigit()

    def _semantic_filter_insights(self, insights: list, query: str | None) -> list:
        """Filter insights by semantic relevance using hybrid keyword + LLM classification."""
        if not query or not insights:
            return insights

        # Step 1: Apply keyword matching for exact matches
        insights_with_keyword_scores = self._apply_keyword_matching(insights, query)

        # Step 2: Apply semantic filtering for nuanced matching
        insights_with_semantic_scores = self._apply_semantic_filtering(insights_with_keyword_scores, query)

        # Step 3: Combine scores and filter
        return self._combine_and_filter_scores(insights_with_semantic_scores)

    def _apply_keyword_matching(self, insights: list, query: str) -> list:
        """Apply keyword matching to boost insights with exact matches in names."""
        query_keywords = query.lower().split()

        for insight in insights:
            name = insight.get("insight__name") or insight.get("insight__derived_name") or ""
            description = insight.get("insight__description") or ""

            # Check for exact keyword matches in name (higher weight)
            name_lower = name.lower()
            name_matches = sum(1 for keyword in query_keywords if keyword in name_lower)

            # Check for exact keyword matches in description (lower weight)
            desc_lower = description.lower()
            desc_matches = sum(1 for keyword in query_keywords if keyword in desc_lower)

            # Calculate keyword score (0.0 to 1.0)
            # Name matches are weighted 3x more than description matches
            total_keywords = len(query_keywords)
            keyword_score = min(1.0, (name_matches * 3 + desc_matches * 1) / (total_keywords * 3))

            insight["keyword_score"] = keyword_score

        return insights

    def _apply_semantic_filtering(self, insights: list, query: str) -> list:
        """Apply LLM-based semantic filtering with improved prompt."""
        # Create insight names for cache key
        insight_names = []
        insights_text = ""
        for i, insight in enumerate(insights, 1):
            name = insight.get("insight__name") or insight.get("insight__derived_name", "Unnamed")
            description = insight.get("insight__description")
            keyword_score = insight.get("keyword_score", 0.0)
            insight_names.append(name)

            # Include keyword score in the prompt to help LLM make better decisions
            score_indicator = "⭐ EXACT MATCH" if keyword_score > 0.5 else "📊"
            if description:
                insights_text += f"{i}. {score_indicator} {name} - {description}\n"
            else:
                insights_text += f"{i}. {score_indicator} {name}\n"

        # Check cache first
        cache_key = self._get_cache_key(query, insight_names)
        cached_ratings, was_cache_hit = self._get_cached_semantic_result(cache_key)

        if not hasattr(self, "_current_cache_hits"):
            self._current_cache_hits = 0
        if not hasattr(self, "_current_cache_misses"):
            self._current_cache_misses = 0

        if was_cache_hit:
            self._current_cache_hits += 1
            ratings = cached_ratings
        else:
            self._current_cache_misses += 1
            # Single LLM call for all insights with improved prompt
            formatted_prompt = self._IMPROVED_SEMANTIC_FILTER_PROMPT.format(
                query=query, insights_list=insights_text.strip()
            )

            model = ChatOpenAI(model="gpt-4o-mini", temperature=0.1, max_completion_tokens=50)

            try:
                response = model.invoke(formatted_prompt)
                ratings_text = response.content.strip()

                # Parse batch response
                ratings = self._parse_batch_ratings(ratings_text, len(insights))

                # Cache the results
                self._cache_semantic_result(cache_key, ratings)

            except Exception as e:
                self.logger.warning(
                    f"Batch semantic filtering failed: {e}, falling back to first {min(3, len(insights))} insights"
                )
                # Fallback: return first few insights with keyword scores
                return [{**insight, "semantic_score": 0.5} for insight in insights[: min(3, len(insights))]]

        # Add semantic scores to insights
        for i, insight in enumerate(insights):
            rating = ratings.get(i + 1, "none")
            if rating == "high":
                semantic_score = 1.0
            elif rating == "medium":
                semantic_score = 0.7
            elif rating == "low":
                semantic_score = 0.3
            else:
                semantic_score = 0.0
            insight["semantic_score"] = semantic_score

        return insights

    def _combine_and_filter_scores(self, insights: list) -> list:
        """Combine keyword and semantic scores, then filter relevant insights."""
        relevant_insights = []

        for insight in insights:
            keyword_score = insight.get("keyword_score", 0.0)
            semantic_score = insight.get("semantic_score", 0.0)

            # Hybrid scoring: keyword matches get significant boost
            if keyword_score >= 0.5:
                # Exact keyword match gets high priority
                if semantic_score >= 1.0:  # high semantic + exact keyword = perfect match
                    final_score = 1.0
                else:
                    final_score = 0.8 + (keyword_score * 0.2)  # 0.8-1.0 range
            elif keyword_score > 0.0:
                # Partial keyword match gets medium priority
                if semantic_score >= 1.0:  # high semantic + partial keyword = very good match
                    final_score = 0.95
                else:
                    final_score = 0.6 + (keyword_score * 0.2) + (semantic_score * 0.2)  # 0.6-1.0 range
            else:
                # No keyword match - rely on semantic score
                final_score = semantic_score  # Preserve original semantic score for backward compatibility

            # Only include insights with reasonable relevance
            if final_score > 0.3:
                relevant_insights.append({**insight, "relevance_score": final_score})

        # Sort by combined relevance score
        return sorted(relevant_insights, key=lambda x: x["relevance_score"], reverse=True)

    def _parse_batch_ratings(self, ratings_text: str, expected_count: int) -> dict[int, str]:
        """Parse batch LLM response into insight ratings."""
        ratings = {}

        lines = ratings_text.split("\n")
        for line in lines:
            line = line.strip()
            if ":" in line:
                try:
                    # Parse format "1: high, 2: medium, 3: low"
                    if "," in line:
                        parts = line.split(",")
                        for part in parts:
                            part = part.strip()
                            if ":" in part:
                                idx_str, rating = part.split(":", 1)
                                idx = int(idx_str.strip())
                                rating = rating.strip().lower()
                                if 1 <= idx <= expected_count:
                                    ratings[idx] = rating
                    else:
                        idx_str, rating = line.split(":", 1)
                        idx = int(idx_str.strip())
                        rating = rating.strip().lower()
                        if 1 <= idx <= expected_count:
                            ratings[idx] = rating
                except (ValueError, IndexError):
                    continue

        # missing ratings
        for i in range(1, expected_count + 1):
            if i not in ratings:
                ratings[i] = "none"

        return ratings

    def _get_full_queries_for_insights(self, filtered_insights: list) -> list:
        """Get full query data for filtered insights with optimized database access."""
        if not filtered_insights:
            return []

        # Extract insight IDs from filtered results
        insight_ids = [insight["insight_id"] for insight in filtered_insights]

        # Optimized query with select_related for performance
        full_insights = (
            Insight.objects.filter(id__in=insight_ids, team=self._team, deleted=False)
            .select_related("team", "created_by")  # Optimize joins
            .values("id", "name", "derived_name", "description", "query", "filters", "short_id")
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
        """Select the single most relevant insight using LLM analysis."""

        if not insights:
            return None

        if not query:
            # return highest relevance score
            return max(insights, key=lambda x: x.get("relevance_score", 0))

        if len(insights) == 1:
            return insights[0]

        # Format for LLM evaluation
        insights_text = ""
        for i, insight in enumerate(insights, 1):
            name = insight.get("name") or insight.get("derived_name", "Unnamed")
            description = insight.get("description")
            query_data = insight.get("query", {})
            filters_data = insight.get("filters", {})

            query_summary = self._summarize_query_data(query_data, filters_data)

            if description:
                insights_text += f"""
{i}. "{name}"
   Description: {description}
   Query: {query_summary}
   Relevance Score: {insight.get('relevance_score', 'N/A')}
"""
            else:
                insights_text += f"""
{i}. "{name}"
   Query: {query_summary}
   Relevance Score: {insight.get('relevance_score', 'N/A')}
"""

        prompt = f"""You are helping a user find the most relevant PostHog insight for their search.

User Search Query: "{query}"

Available Insights:{insights_text}

Select the single most relevant insight by responding with ONLY the number (1, 2, 3, etc.) that best matches the user's search intent.

Most relevant insight number:"""

        model = ChatOpenAI(model="gpt-4o-mini", temperature=0.1, max_completion_tokens=5)

        try:
            response = model.invoke(prompt)
            selection = response.content.strip()

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
                query_summary = self._summarize_query_data(query_data, insight.get("filters", {}))
                result_block += f"\nType: {query_summary}"

            formatted_results.append(result_block)

        content = header + "\n\n".join(formatted_results)

        if len(results) == 1:
            content += "\n\nWould you like me to help you modify this insight or create a similar one?"
        else:
            content += "\n\nWould you like me to help you explore any of these insights further?"

        return content

    @property
    def _model(self):
        return ChatOpenAI(model="gpt-4.1-nano", temperature=0.7, max_completion_tokens=100)
