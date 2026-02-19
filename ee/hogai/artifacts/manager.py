from collections.abc import Sequence
from typing import Literal, cast, overload
from uuid import UUID, uuid4

from langchain_core.runnables import RunnableConfig

from posthog.schema import ArtifactContentType, ArtifactMessage, ArtifactSource, VisualizationMessage

from posthog.models import User
from posthog.models.team import Team

from ee.hogai.artifacts.handlers import (
    EnrichmentContext,
    NotebookArtifactManagerMixin,
    VisualizationArtifactManagerMixin,
    get_handler_for_content_class,
    get_handler_for_content_type,
    get_handler_for_db_type,
)
from ee.hogai.artifacts.types import ArtifactContent, ContentT, StoredContent
from ee.hogai.core.mixins import AssistantContextMixin
from ee.hogai.utils.types.base import ArtifactRefMessage, AssistantMessageUnion
from ee.models.assistant import AgentArtifact


class ArtifactManager(
    VisualizationArtifactManagerMixin,
    NotebookArtifactManagerMixin,
    AssistantContextMixin,
):
    """
    Manages creation and retrieval of agent artifacts.
    """

    def __init__(self, team: Team, user: User, config: RunnableConfig | None = None):
        self._team = team
        self._user = user
        self._config = config or {}

    # -------------------------------------------------------------------------
    # Creation
    # -------------------------------------------------------------------------

    def create_message(
        self,
        artifact_id: str,
        source: ArtifactSource = ArtifactSource.ARTIFACT,
        content_type: ArtifactContentType = ArtifactContentType.VISUALIZATION,
    ) -> ArtifactRefMessage:
        """Create an artifact message."""
        return ArtifactRefMessage(
            content_type=content_type,
            artifact_id=artifact_id,
            source=source,
            id=str(uuid4()),
        )

    async def acreate(
        self,
        content: StoredContent,
        name: str,
    ) -> AgentArtifact:
        """Create and persist an artifact."""
        if not self._config:
            raise ValueError("Config is required")

        conversation = await self._aget_conversation(cast(UUID, self._get_thread_id(self._config)))

        if conversation is None:
            raise ValueError("Conversation not found")

        db_type = self._get_db_type_for_content(content)

        artifact = AgentArtifact(
            name=name[:400],
            type=db_type,
            data=content.model_dump(exclude_none=True),
            conversation=conversation,
            team=self._team,
        )
        await artifact.asave()

        return artifact

    async def aupdate(
        self,
        artifact_id: str,
        content: StoredContent,
    ) -> AgentArtifact:
        """Update an existing artifact."""
        try:
            artifact = await AgentArtifact.objects.aget(short_id=artifact_id, team=self._team)
        except AgentArtifact.DoesNotExist:
            raise ValueError(f"Artifact with short_id={artifact_id} not found")
        artifact.data = content.model_dump(exclude_none=True)
        await artifact.asave()
        return artifact

    # -------------------------------------------------------------------------
    # Content retrieval
    # -------------------------------------------------------------------------

    @overload
    async def aget(self, artifact_id: str, expected_type: type[ContentT]) -> ContentT: ...

    @overload
    async def aget(self, artifact_id: str, expected_type: None = None) -> ArtifactContent: ...

    async def aget(self, artifact_id: str, expected_type: type[ContentT] | None = None) -> ArtifactContent | ContentT:
        """Retrieve artifact content by ID from the database.

        Args:
            artifact_id: The artifact's short ID.
            expected_type: Optional content class to validate and narrow the return type.
                          If provided, raises TypeError if the content doesn't match.

        Returns:
            The artifact content, narrowed to expected_type if provided.

        Raises:
            AgentArtifact.DoesNotExist: If artifact not found.
            TypeError: If expected_type provided but content doesn't match.
        """
        stored_contents = await self._afetch_artifact_contents([artifact_id])
        stored_content = stored_contents.get(artifact_id)
        if stored_content is None:
            raise AgentArtifact.DoesNotExist(f"Artifact with id={artifact_id} not found")

        # Use handler for enrichment (generic for all types)
        handler = get_handler_for_content_class(type(stored_content))
        context = EnrichmentContext(team=self._team)
        content: ArtifactContent = await handler.aenrich(stored_content, context)

        if expected_type is not None and not isinstance(content, expected_type):
            raise TypeError(
                f"Expected content type={expected_type.__name__}, got content type={type(content).__name__}"
            )
        return cast(ContentT, content) if expected_type else content

    async def aenrich_message(
        self,
        message: ArtifactRefMessage,
        state_messages: Sequence[AssistantMessageUnion] | None = None,
    ) -> ArtifactMessage | None:
        """
        Convert an artifact ref message to an enriched artifact message with content.
        Fetches content based on source: State (from messages), Artifact (from DB), or Insight (from DB).
        """
        # Handle visualization artifacts
        if message.source == ArtifactSource.STATE:
            if state_messages is None:
                raise ValueError("state_messages required for State source")
            messages_for_lookup: Sequence[AssistantMessageUnion] = state_messages
        else:
            messages_for_lookup = [message]

        contents = await self._aget_contents_by_id(messages_for_lookup, aggregate_by="message_id")
        content = contents.get(message.id or "")

        if content is None:
            return None

        return self._to_artifact_message(message, content)

    async def aenrich_messages(
        self, messages: Sequence[AssistantMessageUnion], artifacts_only: bool = False
    ) -> list[AssistantMessageUnion | ArtifactMessage]:
        """
        Enrich state messages with artifact content.
        """
        contents_by_id = await self._aget_contents_by_id(messages, aggregate_by="message_id")

        result: list[AssistantMessageUnion | ArtifactMessage] = []
        for message in messages:
            if isinstance(message, ArtifactRefMessage):
                content = contents_by_id.get(message.id or "")
                if content:
                    result.append(self._to_artifact_message(message, content))
            elif not isinstance(message, VisualizationMessage) and not artifacts_only:
                # Pass through non-artifact messages, but skip VisualizationMessage (they are already filtered in the state, just a precaution)
                result.append(message)

        return result

    async def aget_conversation_artifacts(
        self,
        limit: int | None = None,
        offset: int | None = None,
    ) -> tuple[list[ArtifactMessage], int]:
        """Get all artifacts created in a conversation, by the agent and subagents."""
        offset = offset or 0
        conversation_id = cast(UUID, self._get_thread_id(self._config))
        artifacts = AgentArtifact.objects.filter(team=self._team, conversation_id=conversation_id)
        count = await artifacts.acount()

        if limit:
            artifacts = artifacts[offset : offset + limit]
        elif offset:
            artifacts = artifacts[offset:]

        result: list[ArtifactMessage] = []
        async for artifact in artifacts:
            artifact_type = cast(AgentArtifact.Type, artifact.type)
            handler = get_handler_for_db_type(artifact_type)
            if handler is None:
                continue

            stored_content = handler.validate(artifact.data)

            # Use handler for enrichment (generic for all types)
            context = EnrichmentContext(team=self._team)
            content: ArtifactContent = await handler.aenrich(stored_content, context)

            result.append(
                ArtifactMessage(
                    id=artifact.short_id,
                    artifact_id=artifact.short_id,
                    source=ArtifactSource.ARTIFACT,
                    content=content,
                )
            )
        return result, count

    # -------------------------------------------------------------------------
    # Private helpers
    # -------------------------------------------------------------------------

    def _get_db_type_for_content(self, content: StoredContent) -> AgentArtifact.Type:
        """Get the database type for a content object using handlers."""
        handler = get_handler_for_content_class(type(content))
        return handler.db_type

    def _to_artifact_message(self, message: ArtifactRefMessage, content: ArtifactContent) -> ArtifactMessage:
        """Convert an ArtifactRefMessage to an ArtifactMessage."""
        return ArtifactMessage(
            id=message.id,
            artifact_id=message.artifact_id,
            source=message.source,
            content=content,
        )

    async def _afetch_artifact_contents(self, artifact_ids: list[str]) -> dict[str, StoredContent]:
        """Batch fetch artifact contents from the database."""
        if not artifact_ids:
            return {}
        artifacts = AgentArtifact.objects.filter(short_id__in=artifact_ids, team=self._team)
        result: dict[str, StoredContent] = {}
        async for artifact in artifacts:
            artifact_type = cast(AgentArtifact.Type, artifact.type)
            handler = get_handler_for_db_type(artifact_type)
            if handler is None:
                continue
            result[artifact.short_id] = handler.validate(artifact.data)
        return result

    async def _aget_contents_by_id(
        self,
        messages: Sequence[AssistantMessageUnion],
        aggregate_by: Literal["message_id", "artifact_id"] = "message_id",
        filter_by_artifact_ids: list[str] | None = None,
    ) -> dict[str, ArtifactContent]:
        """
        Get artifact content for all artifact messages, keyed by aggregation ID.

        Delegates to handlers which know how to fetch from their supported sources.
        Contents are enriched via handler's enrich method.

        Args:
            messages: The messages to scan for artifact references.
            aggregate_by: How to key results - "message_id" or "artifact_id".
            filter_by_artifact_ids: If provided, only return contents for these artifact IDs.

        Returns:
            Dict mapping aggregation IDs to their artifact content.
        """
        filter_set = set(filter_by_artifact_ids) if filter_by_artifact_ids else None

        # Group messages by content_type, tracking aggregation IDs
        ids_by_content_type: dict[ArtifactContentType, list[str]] = {}
        aggregation_map: dict[str, str] = {}  # artifact_id -> aggregation_id

        for message in messages:
            if not isinstance(message, ArtifactRefMessage) or not message.id:
                continue
            if filter_set and message.artifact_id not in filter_set:
                continue

            aggregation_id = message.id if aggregate_by == "message_id" else message.artifact_id
            aggregation_map[message.artifact_id] = aggregation_id

            if message.content_type not in ids_by_content_type:
                ids_by_content_type[message.content_type] = []
            ids_by_content_type[message.content_type].append(message.artifact_id)

        # Fetch and enrich using handlers
        result: dict[str, ArtifactContent] = {}
        context = EnrichmentContext(team=self._team, state_messages=messages)

        for content_type, artifact_ids in ids_by_content_type.items():
            handler = get_handler_for_content_type(content_type)
            if handler is None:
                continue

            fetch_results = await handler.alist(self._team, artifact_ids, messages)

            for artifact_id, fetch_result in zip(artifact_ids, fetch_results):
                if fetch_result is None:
                    continue
                enriched: ArtifactContent = await handler.aenrich(fetch_result.content, context)
                agg_id = aggregation_map.get(artifact_id)
                if agg_id is not None:
                    result[agg_id] = enriched

        return result
