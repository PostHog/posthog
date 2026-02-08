"""
Sync core memory fragments to the queryable memory system (AgentMemory).

The core memory system stores facts in a flat text format (newline-separated).
The queryable memory system (AgentMemory) stores memories with semantic embeddings.

This module provides helpers to sync core memory fragments to the queryable system,
avoiding duplicates by checking for semantically similar existing memories.
"""

from django.db import transaction

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.models.team import Team
from posthog.models.user import User
from posthog.sync import database_sync_to_async

from products.posthog_ai.backend.models import AgentMemory

EMBEDDING_MODEL = "text-embedding-3-small-1536"
SIMILARITY_THRESHOLD = 0.15  # Cosine distance threshold - lower means more similar


async def sync_memory_to_queryable(
    team: Team,
    user: User | None,
    memory_content: str,
    *,
    similarity_threshold: float = SIMILARITY_THRESHOLD,
) -> AgentMemory | None:
    """
    Add a memory fragment to the queryable memory system if no similar memory exists.

    This function is called automatically when core memory is updated to ensure
    that all core memories are available for semantic search via the queryable
    memory system (AgentMemory with embeddings).

    Duplicate detection: Uses semantic similarity (cosine distance) to check if
    a similar memory already exists. If found (distance < threshold), the sync
    is skipped to prevent duplicates.

    Args:
        team: The team the memory belongs to
        user: The user who created the memory (optional, None for team-wide)
        memory_content: The content to store
        similarity_threshold: Cosine distance threshold for similarity (default 0.15).
                            Lower values require more similarity. Range: 0.0 (identical)
                            to 2.0 (opposite in embedding space).

    Returns:
        The created AgentMemory if a new memory was added, None if a similar one
        already exists or if content is empty.

    Example:
        >>> memory = await sync_memory_to_queryable(
        ...     team=team,
        ...     user=user,
        ...     memory_content="Product uses PostgreSQL database"
        ... )
        >>> if memory:
        ...     print(f"Created memory {memory.id}")
        ... else:
        ...     print("Similar memory already exists")
    """
    if not memory_content or not memory_content.strip():
        return None

    memory_content = memory_content.strip()

    # Check if a similar memory already exists
    if await _has_similar_memory(team, memory_content, similarity_threshold):
        return None

    # Create the new memory
    return await _create_queryable_memory(team, user, memory_content)


async def _has_similar_memory(team: Team, content: str, threshold: float) -> bool:
    """
    Check if a semantically similar memory already exists.

    Uses ClickHouse's cosineDistance function to compute similarity between
    the input content and existing memories. The query embeds the content
    on-the-fly and compares it to stored embeddings.

    Query logic:
    1. Get the latest embedding for each document (using argMax)
    2. Calculate cosine distance between input and each memory
    3. Return true if any memory has distance < threshold

    Args:
        team: Team to check memories for
        content: Text content to check for similarity
        threshold: Maximum cosine distance to consider similar (0.0-2.0)

    Returns:
        True if a similar memory exists (distance < threshold), False otherwise
    """
    query = """
        SELECT
            document_id,
            cosineDistance(embedding, embedText({query_text}, {model_name})) as distance
        FROM (
            SELECT
                document_id,
                argMax(embedding, inserted_at) as embedding
            FROM document_embeddings
            WHERE model_name = {model_name}
              AND product = 'posthog-ai'
              AND document_type = 'memory'
            GROUP BY document_id, model_name, product, document_type, rendering
        )
        WHERE distance < {threshold}
        LIMIT 1
    """

    @database_sync_to_async(thread_sensitive=False)
    def run_query():
        return execute_hogql_query(
            query_type="CoreMemorySimilarityCheck",
            query=query,
            team=team,
            placeholders={
                "query_text": ast.Constant(value=content),
                "model_name": ast.Constant(value=EMBEDDING_MODEL),
                "threshold": ast.Constant(value=threshold),
            },
        )

    result = await run_query()
    return bool(result.results)


async def _create_queryable_memory(team: Team, user: User | None, content: str) -> AgentMemory:
    """
    Create a new AgentMemory and trigger embedding.

    This function creates the AgentMemory record and immediately triggers the
    embedding process by calling memory.embed(). The embedding request is sent
    to the embedding worker via Kafka.

    The created memory is tagged with metadata {"source": "core_memory"} to
    track its origin.

    Args:
        team: Team the memory belongs to
        user: User who created the memory (None for team-wide memories)
        content: Text content to store and embed

    Returns:
        The created AgentMemory instance

    Raises:
        ValueError: If content exceeds 8192 token limit for embedding model
    """

    @database_sync_to_async
    def create():
        with transaction.atomic():
            memory = AgentMemory.objects.create(
                team=team,
                user=user,
                contents=content,
                metadata={"source": "core_memory"},
            )
            memory.embed(EMBEDDING_MODEL)
        return memory

    return await create()
