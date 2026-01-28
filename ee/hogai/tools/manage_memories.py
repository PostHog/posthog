import json
from typing import Any, Literal

from django.db import transaction

from pydantic import BaseModel, Field

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.sync import database_sync_to_async

from products.posthog_ai.backend.models import AgentMemory

from ee.hogai.tool import MaxTool
from ee.hogai.tool_errors import MaxToolRetryableError

EMBEDDING_MODEL = "text-embedding-3-small-1536"

MANAGE_MEMORIES_TOOL_PROMPT = """
Manage persistent memories to remember facts about the user's company, product, and preferences.

A memory is a chunk of text that is searched via semantic embedding, plus metadata allowing you to build up a taxonomy of types or tags for memories over time.

Use memories to:
- Remember user preferences and past interactions
- Store facts about their product, business model, or technical setup
- Track taxonomy relationships and metric definitions
- Save information the user explicitly asks you to remember

Always query memories when you need context about the user's product or when they reference previous discussions.

Store memories pre-emptively - you don't need to be asked specifically to store them, if there's something you think is important, check if there's already a memory about it, and if there isn't, make one.
""".strip()


class CreateMemoryArgs(BaseModel):
    """Store a new memory with content and optional metadata tags."""

    action: Literal["create"]
    contents: str = Field(description="The content of the memory to store")
    metadata: dict | None = Field(default=None, description="Optional metadata tags for the memory")


class QueryMemoryArgs(BaseModel):
    """Search memories using semantic similarity and optional filters."""

    action: Literal["query"]
    query_text: str = Field(description="The search query for finding relevant memories")
    metadata_filter: dict | None = Field(
        default=None, description="Filter by metadata key-value pairs, e.g. {'type': 'preference'}"
    )
    user_only: bool = Field(default=True, description="Search only current user's memories, or all team memories")
    limit: int = Field(default=10, description="Maximum number of results to return")


class UpdateMemoryArgs(BaseModel):
    """Update an existing memory's content or metadata."""

    action: Literal["update"]
    memory_id: str = Field(description="The ID of the memory to update")
    contents: str | None = Field(default=None, description="New content for the memory")
    metadata: dict | None = Field(default=None, description="New metadata for the memory")


class DeleteMemoryArgs(BaseModel):
    """Remove a memory by its ID."""

    action: Literal["delete"]
    memory_id_to_delete: str = Field(description="The ID of the memory to delete")


class ListMetadataKeysArgs(BaseModel):
    """Get all available metadata keys across memories."""

    action: Literal["list_metadata_keys"]


class ManageMemoriesToolArgs(BaseModel):
    args: CreateMemoryArgs | QueryMemoryArgs | UpdateMemoryArgs | DeleteMemoryArgs | ListMetadataKeysArgs = Field(
        discriminator="action",
        description="Arguments for the memory action, with 'action' determining the operation type",
    )


class MemoryResult(BaseModel):
    memory_id: str
    contents: str
    metadata: dict
    distance: float


class ManageMemoriesTool(MaxTool):
    name: Literal["manage_memories"] = "manage_memories"
    description: str = MANAGE_MEMORIES_TOOL_PROMPT
    args_schema: type[BaseModel] = ManageMemoriesToolArgs

    async def _arun_impl(
        self,
        args: CreateMemoryArgs | QueryMemoryArgs | UpdateMemoryArgs | DeleteMemoryArgs | ListMetadataKeysArgs,
    ) -> tuple[str, dict[str, Any]]:
        if isinstance(args, CreateMemoryArgs):
            return await self._create_memory(args.contents, args.metadata)
        elif isinstance(args, QueryMemoryArgs):
            return await self._query_memories(args.query_text, args.metadata_filter, args.user_only, args.limit)
        elif isinstance(args, UpdateMemoryArgs):
            return await self._update_memory(args.memory_id, args.contents, args.metadata)
        elif isinstance(args, DeleteMemoryArgs):
            return await self._delete_memory(args.memory_id_to_delete)
        elif isinstance(args, ListMetadataKeysArgs):
            return await self._list_metadata_keys()

    async def _create_memory(self, contents: str, metadata: dict | None) -> tuple[str, dict[str, Any]]:
        @database_sync_to_async
        def create():
            with transaction.atomic():
                memory = AgentMemory.objects.create(
                    team=self._team,
                    user=self._user,
                    contents=contents,
                    metadata=metadata or {},
                )
                memory.embed(EMBEDDING_MODEL)
            return memory

        memory = await create()
        return (
            f"Memory created successfully with ID: {memory.id}",
            {"memory_id": str(memory.id), "action": "created"},
        )

    async def _query_memories(
        self, query_text: str, metadata_filter: dict | None, user_only: bool, limit: int
    ) -> tuple[str, dict[str, Any]]:
        # Build metadata filter conditions using JSONExtractString with placeholders for both key and value
        metadata_conditions = []
        metadata_placeholders: dict[str, ast.Expr] = {}
        if metadata_filter:
            for i, (key, value) in enumerate(metadata_filter.items()):
                key_placeholder = f"meta_key_{i}"
                value_placeholder = f"meta_value_{i}"
                metadata_conditions.append(
                    f"JSONExtractString(metadata, {{{key_placeholder}}}) = {{{value_placeholder}}}"
                )
                metadata_placeholders[key_placeholder] = ast.Constant(value=key)
                metadata_placeholders[value_placeholder] = ast.Constant(value=str(value))

        metadata_filter_sql = " AND ".join(metadata_conditions) if metadata_conditions else "1=1"

        # This query isn't particularly optimal, but the universe of memories per team is going to be
        # so small that it really doesn't need to be - we don't need to try and pick up on the vector
        # indexes or anything, pure brute force search is fine.
        query = f"""
            SELECT
                document_id,
                content,
                metadata,
                cosineDistance(embedding, embedText({{query_text}}, {{model_name}})) as distance
            FROM (
                SELECT
                    document_id,
                    argMax(content, inserted_at) as content,
                    argMax(metadata, inserted_at) as metadata,
                    argMax(embedding, inserted_at) as embedding
                FROM document_embeddings
                WHERE model_name = {{model_name}}
                  AND product = 'posthog-ai'
                  AND document_type = 'memory'
                GROUP BY document_id, model_name, product, document_type, rendering
            )
            WHERE ({{skip_user_filter}} OR JSONExtractString(metadata, 'user_id') = {{user_id}})
              AND NOT JSONExtractBool(metadata, 'deleted')
              AND ({metadata_filter_sql})
            ORDER BY distance ASC
            LIMIT {{limit}}
        """

        user_id = str(self._user.id) if self._user else ""
        skip_user_filter = not user_only or not self._user

        @database_sync_to_async(thread_sensitive=False)
        def run_query():
            return execute_hogql_query(
                query_type="ManageMemoriesTool",
                query=query,
                team=self._team,
                placeholders={
                    "query_text": ast.Constant(value=query_text),
                    "model_name": ast.Constant(value=EMBEDDING_MODEL),
                    "user_id": ast.Constant(value=user_id),
                    "skip_user_filter": ast.Constant(value=skip_user_filter),
                    "limit": ast.Constant(value=limit),
                    **metadata_placeholders,
                },
            )

        result = await run_query()

        memories: list[MemoryResult] = []
        for row in result.results or []:
            document_id, content, metadata_str, distance = row
            try:
                metadata_dict = json.loads(metadata_str) if isinstance(metadata_str, str) else metadata_str or {}
            except json.JSONDecodeError:
                metadata_dict = {}

            memories.append(
                MemoryResult(
                    memory_id=document_id,
                    contents=content,
                    metadata=metadata_dict,
                    distance=distance,
                )
            )

        if not memories:
            return "No memories found matching your query.", {"results": [], "count": 0}

        result_text = f"Found {len(memories)} relevant memories:\n\n"
        for i, mem in enumerate(memories, 1):
            result_text += f"**Memory {i}** (ID: {mem.memory_id}, distance: {mem.distance:.4f})\n"
            result_text += f"Content: {mem.contents}\n"
            if mem.metadata:
                result_text += f"Metadata: {json.dumps(mem.metadata)}\n"
            result_text += "\n"

        return result_text, {
            "results": [m.model_dump() for m in memories],
            "count": len(memories),
        }

    async def _update_memory(
        self, memory_id: str, contents: str | None, metadata: dict | None
    ) -> tuple[str, dict[str, Any]]:
        if contents is None and metadata is None:
            raise MaxToolRetryableError("At least one of contents or metadata must be provided for update action")

        @database_sync_to_async
        def update():
            try:
                memory = AgentMemory.objects.get(id=memory_id, team=self._team)
            except AgentMemory.DoesNotExist:
                return None

            if contents is not None:
                memory.contents = contents
            if metadata is not None:
                memory.metadata = metadata
            memory.user = self._user

            with transaction.atomic():
                memory.save()
                memory.embed(EMBEDDING_MODEL)
            return memory

        memory = await update()
        if not memory:
            raise MaxToolRetryableError(f"Memory with ID {memory_id} not found")

        return (
            f"Memory {memory_id} updated successfully",
            {"memory_id": str(memory.id), "action": "updated"},
        )

    async def _delete_memory(self, memory_id: str) -> tuple[str, dict[str, Any]]:
        @database_sync_to_async
        def delete():
            try:
                memory = AgentMemory.objects.get(id=memory_id, team=self._team)
            except AgentMemory.DoesNotExist:
                return None

            memory.metadata = {**memory.metadata, "deleted": True}
            with transaction.atomic():
                memory.embed(EMBEDDING_MODEL)
                memory.delete()
            return memory_id

        deleted_id = await delete()
        if not deleted_id:
            raise MaxToolRetryableError(f"Memory with ID {memory_id} not found")

        return (
            f"Memory {memory_id} deleted successfully",
            {"memory_id": deleted_id, "action": "deleted"},
        )

    async def _list_metadata_keys(self) -> tuple[str, dict[str, Any]]:
        @database_sync_to_async(thread_sensitive=False)
        def get_keys():
            memories = AgentMemory.objects.filter(team=self._team).values_list("metadata", flat=True)
            all_keys: set[str] = set()
            for metadata in memories:
                if isinstance(metadata, dict):
                    all_keys.update(metadata.keys())
            return sorted(all_keys)

        keys = await get_keys()

        if not keys:
            return "No metadata keys found in any memories.", {"keys": []}

        return (
            f"Available metadata keys across all memories: {', '.join(keys)}",
            {"keys": keys},
        )
