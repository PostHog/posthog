from collections.abc import Sequence
from typing import Literal, TypeVar, cast, overload
from uuid import UUID, uuid4

from langchain_core.runnables import RunnableConfig
from posthoganalytics import capture_exception
from pydantic import BaseModel, ValidationError

from posthog.schema import (
    ArtifactContentType,
    ArtifactMessage,
    ArtifactSource,
    NotebookArtifactContent,
    VisualizationArtifactContent,
    VisualizationMessage,
)

from posthog.models import Insight, User
from posthog.models.team import Team

from ee.hogai.core.mixins import AssistantContextMixin
from ee.hogai.utils.supported_queries import SUPPORTED_QUERY_MODEL_BY_KIND
from ee.hogai.utils.types.base import ArtifactRefMessage, AssistantMessageUnion
from ee.models.assistant import AgentArtifact

Content = VisualizationArtifactContent | NotebookArtifactContent
ContentT = TypeVar("ContentT", bound=Content)


class ArtifactTypeConfig[T: BaseModel]:
    """Configuration for an artifact type, mapping between schema, DB type, and content type."""

    def __init__(
        self,
        content_class: type[T],
        db_type: AgentArtifact.Type,
        content_type: ArtifactContentType,
    ):
        self.content_class = content_class
        self.db_type = db_type
        self.content_type = content_type


# Registry mapping content classes to their configuration
# Add new artifact types here - no other changes needed in the manager
ARTIFACT_TYPE_REGISTRY: dict[type[Content], ArtifactTypeConfig[Content]] = {
    VisualizationArtifactContent: ArtifactTypeConfig(
        content_class=VisualizationArtifactContent,
        db_type=AgentArtifact.Type.VISUALIZATION,
        content_type=ArtifactContentType.VISUALIZATION,
    ),
    NotebookArtifactContent: ArtifactTypeConfig(
        content_class=NotebookArtifactContent,
        db_type=AgentArtifact.Type.NOTEBOOK,
        content_type=ArtifactContentType.NOTEBOOK,
    ),
}

# Reverse lookup: DB type -> content class
DB_TYPE_TO_CONTENT_CLASS: dict[AgentArtifact.Type, type[Content]] = {
    config.db_type: config.content_class for config in ARTIFACT_TYPE_REGISTRY.values()
}


class ArtifactManager(AssistantContextMixin):
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

    async def create(
        self,
        content: Content,
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

    def _get_db_type_for_content(self, content: Content) -> AgentArtifact.Type:
        """Get the database type for a content object using the registry."""
        for content_class, config in ARTIFACT_TYPE_REGISTRY.items():
            if isinstance(content, content_class):
                return config.db_type
        raise ValueError(f"Unknown content type={type(content).__name__}")

    async def update(
        self,
        artifact_id: str,
        content: Content,
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
    async def aget_content_by_short_id(self, short_id: str, expected_type: type[ContentT]) -> ContentT: ...

    @overload
    async def aget_content_by_short_id(self, short_id: str, expected_type: None = None) -> Content: ...

    async def aget_content_by_short_id(
        self, short_id: str, expected_type: type[ContentT] | None = None
    ) -> Content | ContentT:
        """Retrieve artifact content by short_id.

        Args:
            short_id: The artifact's short ID.
            expected_type: Optional content class to validate and narrow the return type.
                          If provided, raises TypeError if the content doesn't match.

        Returns:
            The artifact content, narrowed to expected_type if provided.

        Raises:
            AgentArtifact.DoesNotExist: If artifact not found.
            TypeError: If expected_type provided but content doesn't match.
        """
        contents = await self._afetch_artifact_contents([short_id])
        content = contents.get(short_id)
        if content is None:
            raise AgentArtifact.DoesNotExist(f"Artifact with short_id={short_id} not found")
        if expected_type is not None and not isinstance(content, expected_type):
            raise TypeError(
                f"Expected content type={expected_type.__name__}, got content type={type(content).__name__}"
            )
        return content

    async def aget_enriched_message(
        self,
        message: ArtifactRefMessage,
        state_messages: Sequence[AssistantMessageUnion] | None = None,
    ) -> ArtifactMessage | None:
        """
        Convert an artifact message to an enriched artifact message.
        Fetches content based on source: State (from messages), Artifact (from DB), or Insight (from DB).
        """
        # Handle visualization artifacts
        if message.source == ArtifactSource.STATE:
            if state_messages is None:
                raise ValueError("state_messages required for State source")
            messages_for_lookup: Sequence[AssistantMessageUnion] = state_messages
        else:
            messages_for_lookup = [message]

        contents = await self.aget_contents_by_id(messages_for_lookup, aggregate_by="message_id")
        content = contents.get(message.id or "")

        if content is None:
            return None

        return self._to_artifact_message(message, content)

    async def aget_contents_by_id(
        self,
        messages: Sequence[AssistantMessageUnion],
        aggregate_by: Literal["message_id", "artifact_id"] = "message_id",
        filter_by_artifact_ids: list[str] | None = None,
    ) -> dict[str, Content]:
        """
        Get artifact content for all artifact messages, keyed by message ID.

        If filter_by_artifact_ids is provided, only return contents for the given artifact IDs.
        """
        result: dict[str, Content] = {}
        # Collect IDs by source
        artifact_ids: list[str] = []
        insight_ids: list[str] = []
        artifact_id_to_aggregation_id: dict[str, str] = {}
        insight_id_to_aggregation_id: dict[str, str] = {}

        for message in messages:
            if not isinstance(message, ArtifactRefMessage):
                continue
            if not message.id:
                continue
            aggregation_id = message.id if aggregate_by == "message_id" else message.artifact_id
            if message.source == ArtifactSource.STATE:
                content = self._content_from_state(message.artifact_id, messages)
                if content:
                    result[aggregation_id] = content
            elif message.source == ArtifactSource.ARTIFACT:
                artifact_ids.append(message.artifact_id)
                artifact_id_to_aggregation_id[message.artifact_id] = aggregation_id
            elif message.source == ArtifactSource.INSIGHT:
                insight_ids.append(message.artifact_id)
                insight_id_to_aggregation_id[message.artifact_id] = aggregation_id

        if filter_by_artifact_ids:
            artifact_ids = [aid for aid in artifact_ids if aid in filter_by_artifact_ids]
            insight_ids = [aid for aid in insight_ids if aid in filter_by_artifact_ids]

        # Batch fetch from DB
        artifact_contents = await self._afetch_artifact_contents(artifact_ids)
        insight_contents = await self._afetch_insight_contents(insight_ids)

        for artifact_id, artifact_content in artifact_contents.items():
            artifact_aggregation_id = artifact_id_to_aggregation_id.get(artifact_id)
            if artifact_aggregation_id:
                result[artifact_aggregation_id] = artifact_content
        for insight_id, insight_content in insight_contents.items():
            insight_aggregation_id = insight_id_to_aggregation_id.get(insight_id)
            if insight_aggregation_id:
                result[insight_aggregation_id] = insight_content

        return result

    async def aenrich_messages(
        self, messages: Sequence[AssistantMessageUnion], artifacts_only: bool = False
    ) -> list[AssistantMessageUnion | ArtifactMessage]:
        """
        Enrich state messages with artifact content.
        """
        contents_by_id = await self.aget_contents_by_id(messages, aggregate_by="message_id")

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

    # -------------------------------------------------------------------------
    # Private helpers
    # -------------------------------------------------------------------------

    def _content_from_state(
        self, artifact_id: str, messages: Sequence[AssistantMessageUnion]
    ) -> VisualizationArtifactContent | None:
        """Extract content from a VisualizationMessage in state.

        Field mappings from VisualizationMessage to VisualizationArtifactContent:
        - answer -> query: The actual query object (e.g., TrendsQuery)
        - query -> name: The user's original query text (used as chart title)
        - plan -> description: The agent's plan/explanation
        """
        for msg in messages:
            if isinstance(msg, VisualizationMessage) and msg.id == artifact_id:
                try:
                    return VisualizationArtifactContent(
                        query=msg.answer,
                        name=msg.query,
                        description=msg.plan,
                    )
                except ValidationError as e:
                    capture_exception(e)
                    # Old unsupported visualization messages schemas
                    return None
        return None

    def _to_artifact_message(self, message: ArtifactRefMessage, content: Content) -> ArtifactMessage:
        """Convert an ArtifactRefMessage to an ArtifactMessage."""
        return ArtifactMessage(
            id=message.id,
            artifact_id=message.artifact_id,
            source=message.source,
            content=content,
        )

    async def _afetch_artifact_contents(self, artifact_ids: list[str]) -> dict[str, Content]:
        """Batch fetch artifact contents from the database."""
        if not artifact_ids:
            return {}
        artifacts = AgentArtifact.objects.filter(short_id__in=artifact_ids, team=self._team)
        result: dict[str, Content] = {}
        async for artifact in artifacts:
            artifact_type = cast(AgentArtifact.Type, artifact.type)
            content_class = DB_TYPE_TO_CONTENT_CLASS.get(artifact_type)
            if content_class:
                result[artifact.short_id] = content_class.model_validate(artifact.data)
        return result

    async def _afetch_insight_contents(self, insight_ids: list[str]) -> dict[str, VisualizationArtifactContent]:
        """Batch fetch insight contents from the database."""
        if not insight_ids:
            return {}
        insights = Insight.objects.filter(short_id__in=insight_ids, team=self._team)
        result: dict[str, VisualizationArtifactContent] = {}
        async for insight in insights:
            query = insight.query
            if not query:
                continue
            # Insights store queries wrapped in InsightVizNode, extract the inner query
            if isinstance(query, dict) and query.get("source"):
                query = query.get("source")
            if not query:
                continue
            # Validate and convert dict to model
            query_kind = query.get("kind") if isinstance(query, dict) else None
            if not query_kind or query_kind not in SUPPORTED_QUERY_MODEL_BY_KIND:
                continue
            try:
                QueryModel = SUPPORTED_QUERY_MODEL_BY_KIND[query_kind]
                query_obj = QueryModel.model_validate(query)
                result[insight.short_id] = VisualizationArtifactContent(
                    query=query_obj,
                    name=insight.name or insight.derived_name,
                    description=insight.description,
                )
            except Exception as e:
                capture_exception(e)
                continue
        return result
