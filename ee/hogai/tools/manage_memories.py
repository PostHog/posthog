import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.sync import database_sync_to_async

from ee.hogai.tool import MaxTool
from ee.hogai.tool_errors import MaxToolRetryableError

EMBEDDING_MODEL = "text-embedding-3-small-1536"

MANAGE_MEMORIES_TOOL_PROMPT = """
Manage persistent memories to remember facts about the user's company, product, and preferences.

Actions:
- **create**: Store a new memory with content and optional metadata
- **query**: Search for relevant memories using semantic search
- **update**: Modify an existing memory by its ID (content and/or metadata)
- **list_metadata_keys**: Get all metadata keys used across memories (to know what you can filter by)

Query Options:
- user_only (default: true): Search only current user's memories, or all team memories
- limit: Maximum results (default: 10)

Returns for query: memory_id, contents, metadata (as dict), distance score

Use memories to:
- Remember user preferences and past interactions
- Store facts about their product, business model, or technical setup
- Track taxonomy relationships and metric definitions
- Save information the user explicitly asks you to remember

Always query memories when you need context about the user's product or when they reference previous discussions.
""".strip()


class ManageMemoriesToolArgs(BaseModel):
    action: Literal["create", "query", "update", "list_metadata_keys"] = Field(
        description="The action to perform on memories"
    )
    contents: str | None = Field(default=None, description="The content of the memory (for create/update)")
    metadata: dict | None = Field(
        default=None, description="Optional metadata to attach to the memory (for create/update)"
    )
    memory_id: str | None = Field(default=None, description="The ID of the memory to update (for update action)")
    query_text: str | None = Field(
        default=None, description="The search query for finding relevant memories (for query action)"
    )
    user_only: bool = Field(
        default=True, description="If true, search only current user's memories; if false, search all team memories"
    )
    limit: int = Field(default=10, description="Maximum number of results to return (for query action)")


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
        action: str,
        contents: str | None = None,
        metadata: dict | None = None,
        memory_id: str | None = None,
        query_text: str | None = None,
        user_only: bool = True,
        limit: int = 10,
    ) -> tuple[str, dict[str, Any]]:
        if action == "create":
            return await self._create_memory(contents, metadata)
        elif action == "query":
            return await self._query_memories(query_text, user_only, limit)
        elif action == "update":
            return await self._update_memory(memory_id, contents, metadata)
        elif action == "list_metadata_keys":
            return await self._list_metadata_keys()
        else:
            raise MaxToolRetryableError(
                f"Unknown action: {action}. Valid actions are: create, query, update, list_metadata_keys"
            )

    async def _create_memory(self, contents: str | None, metadata: dict | None) -> tuple[str, dict[str, Any]]:
        if not contents:
            raise MaxToolRetryableError("contents is required for create action")

        from products.posthog_ai.backend.models import AgentMemory

        @database_sync_to_async
        def create():
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

    async def _query_memories(self, query_text: str | None, user_only: bool, limit: int) -> tuple[str, dict[str, Any]]:
        if not query_text:
            raise MaxToolRetryableError("query_text is required for query action")

        query = """
            SELECT
                document_id,
                content,
                metadata,
                cosineDistance(embedding, embedText({query_text}, {model_name})) as distance
            FROM document_embeddings
            WHERE team_id = {team_id}
              AND model_name = {model_name}
              AND product = 'posthog-ai'
              AND document_type = 'memory'
              AND ({skip_user_filter} OR JSONExtractString(metadata, 'user_id') = {user_id})
            ORDER BY distance ASC
            LIMIT {limit}
        """

        user_id = str(self._user.id) if self._user else ""
        skip_user_filter = not user_only or not self._user

        @database_sync_to_async
        def run_query():
            return execute_hogql_query(
                query_type="ManageMemoriesTool",
                query=query,
                team=self._team,
                placeholders={
                    "query_text": ast.Constant(value=query_text),
                    "team_id": ast.Constant(value=self._team.id),
                    "model_name": ast.Constant(value=EMBEDDING_MODEL),
                    "user_id": ast.Constant(value=user_id),
                    "skip_user_filter": ast.Constant(value=skip_user_filter),
                    "limit": ast.Constant(value=limit),
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
        self, memory_id: str | None, contents: str | None, metadata: dict | None
    ) -> tuple[str, dict[str, Any]]:
        if not memory_id:
            raise MaxToolRetryableError("memory_id is required for update action")
        if contents is None and metadata is None:
            raise MaxToolRetryableError("At least one of contents or metadata must be provided for update action")

        from products.posthog_ai.backend.models import AgentMemory

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

    async def _list_metadata_keys(self) -> tuple[str, dict[str, Any]]:
        from products.posthog_ai.backend.models import AgentMemory

        @database_sync_to_async
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
