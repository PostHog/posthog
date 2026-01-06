import time
import asyncio
from typing import Any

from django.conf import settings

import posthoganalytics
from azure.core.exceptions import HttpResponseError as AzureHttpResponseError
from prometheus_client import Histogram

from posthog.schema import CachedVectorSearchQueryResponse, VectorSearchQuery

from posthog.api.search import search_entities
from posthog.clickhouse.query_tagging import Product, tags_context
from posthog.hogql_queries.ai.vector_search_query_runner import (
    LATEST_ACTIONS_EMBEDDING_VERSION,
    VectorSearchQueryRunner,
)
from posthog.hogql_queries.query_runner import ExecutionMode
from posthog.models import Action
from posthog.rbac.user_access_control import UserAccessControl
from posthog.sync import database_sync_to_async

from ee.hogai.tool import MaxSubtool
from ee.hogai.tools.full_text_search.tool import ENTITY_MAP
from ee.hogai.utils.embeddings import aembed_search_query, get_async_azure_embeddings_client

HYBRID_SEARCH_VECTOR_TIMING_HISTOGRAM = Histogram(
    "posthog_ai_hybrid_search_vector_duration_seconds",
    "Time for vector search in hybrid action search",
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, float("inf")],
)

HYBRID_SEARCH_FTS_TIMING_HISTOGRAM = Histogram(
    "posthog_ai_hybrid_search_fts_duration_seconds",
    "Time for FTS in hybrid action search",
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, float("inf")],
)

HYBRID_SEARCH_TOTAL_TIMING_HISTOGRAM = Histogram(
    "posthog_ai_hybrid_search_total_duration_seconds",
    "Total time for hybrid action search",
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, float("inf")],
)


class HybridActionSearchTool(MaxSubtool):
    """
    Hybrid search for Actions combining vector search (semantic) with FTS (keyword),
    using Reciprocal Rank Fusion (RRF) for reranking.

    RRF Formula: score(d) = Σ 1/(k + rank(d)) for each retriever
    - k=60 is the standard constant that balances contribution of top vs. lower-ranked results
    - No score normalization needed - works directly with ranks
    """

    RRF_K = 60  # Standard RRF constant
    MAX_RESULTS = 10

    async def execute(self, query: str) -> list[dict[str, Any]]:
        """
        Execute hybrid search combining vector and FTS results.

        Returns list of action dicts with: id, name, description, rrf_score, sources
        """
        total_start = time.time()

        try:
            # Run both searches in parallel
            vector_task = self._vector_search(query)
            fts_task = self._fts_search(query)

            results = await asyncio.gather(vector_task, fts_task, return_exceptions=True)
            vector_results = results[0] if not isinstance(results[0], BaseException) else []
            fts_results = results[1] if not isinstance(results[1], BaseException) else []

            # Log exceptions but continue with available results
            for i, result in enumerate(results):
                if isinstance(result, BaseException):
                    source = "vector" if i == 0 else "fts"
                    posthoganalytics.capture_exception(
                        result,
                        distinct_id=self._user.distinct_id,
                        properties={"source": source, "query": query},
                    )

            # Apply RRF reranking
            merged_ids = self._reciprocal_rank_fusion(vector_results, fts_results)

            if not merged_ids:
                return []

            # Fetch action details
            actions = await self._fetch_actions(merged_ids[: self.MAX_RESULTS])

            # Build result with metadata
            vector_id_set = {id for id, _ in vector_results}
            fts_id_set = {id for id, _ in fts_results}

            result = []
            for action in actions:
                action_id = str(action.id)
                sources = []
                if action_id in vector_id_set:
                    sources.append("vector")
                if action_id in fts_id_set:
                    sources.append("fts")

                result.append(
                    {
                        "id": action_id,
                        "name": action.name,
                        "description": action.description,
                        "sources": sources,
                    }
                )

            return result

        finally:
            HYBRID_SEARCH_TOTAL_TIMING_HISTOGRAM.observe(time.time() - total_start)

    async def _vector_search(self, query: str) -> list[tuple[str, float]]:
        """
        Perform vector search using embeddings.

        Returns list of (action_id, distance) sorted by distance ASC (lower = better).
        """
        start_time = time.time()
        try:
            if not settings.AZURE_INFERENCE_ENDPOINT or not settings.AZURE_INFERENCE_CREDENTIAL:
                return []

            async with get_async_azure_embeddings_client() as client:
                embedding = await aembed_search_query(client, query)

            runner = VectorSearchQueryRunner(
                team=self._team,
                query=VectorSearchQuery(embedding=embedding, embeddingVersion=LATEST_ACTIONS_EMBEDDING_VERSION),
            )

            with tags_context(product=Product.MAX_AI, team_id=self._team.pk, org_id=self._team.organization_id):
                response = await database_sync_to_async(runner.run, thread_sensitive=False)(
                    ExecutionMode.RECENT_CACHE_CALCULATE_BLOCKING_IF_STALE
                )

            if isinstance(response, CachedVectorSearchQueryResponse) and response.results:
                return [(row.id, row.distance) for row in response.results]

            return []

        except (AzureHttpResponseError, ValueError):
            # Will be caught and logged by the caller
            raise
        finally:
            HYBRID_SEARCH_VECTOR_TIMING_HISTOGRAM.observe(time.time() - start_time)

    async def _fts_search(self, query: str) -> list[tuple[str, float]]:
        """
        Perform full-text search using PostgreSQL.

        Returns list of (action_id, rank) sorted by rank DESC (higher = better).
        """
        start_time = time.time()
        try:
            results, _ = await database_sync_to_async(search_entities, thread_sensitive=False)(
                {"action"},
                query,
                self._team.project_id,
                self,
                ENTITY_MAP,
            )

            return [(r["result_id"], r.get("rank", 0)) for r in results]

        finally:
            HYBRID_SEARCH_FTS_TIMING_HISTOGRAM.observe(time.time() - start_time)

    def _reciprocal_rank_fusion(
        self,
        vector_results: list[tuple[str, float]],
        fts_results: list[tuple[str, float]],
    ) -> list[str]:
        """
        Merge results using Reciprocal Rank Fusion (RRF).

        RRF score = Σ 1/(k + rank) for each retriever where result appears.

        Args:
            vector_results: List of (id, distance) from vector search, sorted by distance ASC
            fts_results: List of (id, rank) from FTS, sorted by rank DESC

        Returns:
            List of action IDs sorted by RRF score DESC (best first)
        """
        # Convert to 1-indexed ranks
        vector_ranks = {id: i + 1 for i, (id, _) in enumerate(vector_results)}
        fts_ranks = {id: i + 1 for i, (id, _) in enumerate(fts_results)}

        all_ids = set(vector_ranks.keys()) | set(fts_ranks.keys())

        rrf_scores: dict[str, float] = {}
        for id in all_ids:
            score = 0.0
            if id in vector_ranks:
                score += 1.0 / (self.RRF_K + vector_ranks[id])
            if id in fts_ranks:
                score += 1.0 / (self.RRF_K + fts_ranks[id])
            rrf_scores[id] = score

        return sorted(all_ids, key=lambda x: rrf_scores[x], reverse=True)

    async def _fetch_actions(self, action_ids: list[str]) -> list[Action]:
        """Fetch actions from database, preserving the order of action_ids."""
        if not action_ids:
            return []

        actions = [
            action
            async for action in Action.objects.filter(
                team__project_id=self._team.project_id,
                id__in=action_ids,
                deleted=False,
            ).only("id", "name", "description")
        ]

        # Preserve ordering from RRF ranking
        action_map = {str(a.id): a for a in actions}
        return [action_map[id] for id in action_ids if id in action_map]

    # Required for search_entities compatibility
    @property
    def user_access_control(self):
        return UserAccessControl(user=self._user, team=self._team, organization_id=self._team.organization.id)
