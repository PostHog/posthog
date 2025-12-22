from collections.abc import Sequence
from typing import Generic, Literal, TypeVar, cast
from uuid import UUID, uuid4

from langchain_core.runnables import RunnableConfig
from posthoganalytics import capture_exception
from pydantic import BaseModel, ConfigDict, ValidationError

from posthog.schema import (
    ArtifactContentType,
    ArtifactMessage,
    ArtifactSource,
    DocumentArtifactContent,
    VisualizationArtifactContent,
    VisualizationMessage,
)

from posthog.models import Insight, User
from posthog.models.team import Team

from ee.hogai.context.insight.context import InsightContext
from ee.hogai.core.mixins import AssistantContextMixin
from ee.hogai.utils.types.base import ArtifactRefMessage, AssistantMessageUnion
from ee.models.assistant import AgentArtifact

ArtifactContentUnion = DocumentArtifactContent | VisualizationArtifactContent

T = TypeVar("T", bound=ArtifactContentUnion)
S = TypeVar("S", bound=ArtifactSource)
M = TypeVar("M")


class StateArtifactResult(BaseModel, Generic[T]):
    source: Literal[ArtifactSource.STATE] = ArtifactSource.STATE
    content: T


class DatabaseArtifactResult(BaseModel, Generic[T]):
    source: Literal[ArtifactSource.ARTIFACT] = ArtifactSource.ARTIFACT
    content: T


class ModelArtifactResult(BaseModel, Generic[T, S, M]):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    source: S
    content: T
    model: M


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
        content: VisualizationArtifactContent,
        name: str,
    ) -> AgentArtifact:
        """Create and persist an artifact."""
        if not self._config:
            raise ValueError("Config is required")

        conversation = await self._aget_conversation(cast(UUID, self._get_thread_id(self._config)))

        if conversation is None:
            raise ValueError("Conversation not found")

        artifact = AgentArtifact(
            name=name[:400],
            type=AgentArtifact.Type.VISUALIZATION,
            data=content.model_dump(exclude_none=True),
            conversation=conversation,
            team=self._team,
        )
        await artifact.asave()

        return artifact

    # -------------------------------------------------------------------------
    # Content retrieval
    # -------------------------------------------------------------------------

    async def aget_content_by_short_id(self, short_id: str) -> VisualizationArtifactContent:
        """Retrieve visualization content from an artifact by short_id."""
        contents = await self._afetch_artifact_contents([short_id])
        content = contents.get(short_id)
        if content is None:
            raise AgentArtifact.DoesNotExist(f"Artifact with short_id={short_id} not found")
        return content

    InsightWithSourceResult = (
        StateArtifactResult[VisualizationArtifactContent]
        | DatabaseArtifactResult[VisualizationArtifactContent]
        | ModelArtifactResult[VisualizationArtifactContent, Literal[ArtifactSource.INSIGHT], Insight]
    )

    async def aget_insights_with_source(
        self, state_messages: Sequence[AssistantMessageUnion], artifact_ids: list[str]
    ) -> list[InsightWithSourceResult | None]:
        """
        Retrieve artifact content for multiple IDs along with their sources.
        Checks state first, then artifacts, then insights.
        Returns ordered list matching input artifact_ids (None for missing IDs).
        """
        if not artifact_ids:
            return []

        remaining_artifact_ids = set(artifact_ids)
        results_map: dict[str, ArtifactManager.InsightWithSourceResult] = {}

        # Try state first if messages provided
        for artifact_id in artifact_ids:
            content = self._content_from_state(artifact_id, state_messages)
            if content is None:
                continue
            results_map[artifact_id] = StateArtifactResult(content=content)
            remaining_artifact_ids.remove(artifact_id)

        # Find IDs still not resolved in state
        if remaining_artifact_ids:
            # Batch fetch artifacts
            artifact_contents = await self._afetch_artifact_contents(list(remaining_artifact_ids))
            for artifact_id, content in artifact_contents.items():
                results_map[artifact_id] = DatabaseArtifactResult(content=content)
                remaining_artifact_ids.remove(artifact_id)

        # Find IDs still not resolved
        if remaining_artifact_ids:
            # Batch fetch insights
            insight_results = await self._afetch_insights_with_models(list(remaining_artifact_ids))
            for artifact_id, (content, insight) in insight_results.items():
                results_map[artifact_id] = ModelArtifactResult(
                    source=ArtifactSource.INSIGHT,
                    content=content,
                    model=insight,
                )
                remaining_artifact_ids.remove(artifact_id)

        # Return ordered list matching input
        return [results_map.get(artifact_id) for artifact_id in artifact_ids]

    async def aget_insight_with_source(
        self, state_messages: Sequence[AssistantMessageUnion], artifact_id: str
    ) -> InsightWithSourceResult | None:
        """
        Retrieve artifact content by ID along with its source.
        Checks state first, then artifacts, then insights.
        Returns content or None if not found.
        """
        results = await self.aget_insights_with_source(state_messages, [artifact_id])
        return results[0] if results else None

    async def aget_enriched_message(
        self,
        message: ArtifactRefMessage,
        state_messages: Sequence[AssistantMessageUnion] | None = None,
    ) -> ArtifactMessage | None:
        """
        Convert an artifact message to a visualization artifact message.
        Fetches content based on source: State (from messages), Artifact (from DB), or Insight (from DB).
        """
        if message.source == ArtifactSource.STATE:
            if state_messages is None:
                raise ValueError("state_messages required for State source")
            messages_for_lookup: Sequence[AssistantMessageUnion] = state_messages
        else:
            messages_for_lookup = [message]

        contents = await self.aget_contents_by_message_id(messages_for_lookup)
        content = contents.get(message.id or "")

        if content is None:
            return None

        return self._to_visualization_artifact_message(message, content)

    async def aget_contents_by_message_id(
        self, messages: Sequence[AssistantMessageUnion]
    ) -> dict[str, VisualizationArtifactContent]:
        """
        Get artifact content for all artifact messages, keyed by message ID.
        """
        result: dict[str, VisualizationArtifactContent] = {}

        # Collect IDs by source
        artifact_ids: list[str] = []
        insight_ids: list[str] = []
        artifact_id_to_message_id: dict[str, str] = {}
        insight_id_to_message_id: dict[str, str] = {}

        for message in messages:
            if not isinstance(message, ArtifactRefMessage):
                continue
            if not message.id:
                continue
            if message.source == ArtifactSource.STATE:
                content = self._content_from_state(message.artifact_id, messages)
                if content:
                    result[message.id] = content
            elif message.source == ArtifactSource.ARTIFACT:
                artifact_ids.append(message.artifact_id)
                artifact_id_to_message_id[message.artifact_id] = message.id
            elif message.source == ArtifactSource.INSIGHT:
                insight_ids.append(message.artifact_id)
                insight_id_to_message_id[message.artifact_id] = message.id

        # Batch fetch from DB
        artifact_contents = await self._afetch_artifact_contents(artifact_ids)
        insight_contents = await self._afetch_insight_contents(insight_ids)

        for artifact_id, content in artifact_contents.items():
            if message_id := artifact_id_to_message_id.get(artifact_id):
                result[message_id] = content
        for insight_id, content in insight_contents.items():
            if message_id := insight_id_to_message_id.get(insight_id):
                result[message_id] = content

        return result

    async def aenrich_messages(
        self, messages: Sequence[AssistantMessageUnion], artifacts_only: bool = False
    ) -> list[AssistantMessageUnion | ArtifactMessage]:
        """
        Enrich state messages with artifact content.
        """
        contents_by_id = await self.aget_contents_by_message_id(messages)

        result: list[AssistantMessageUnion | ArtifactMessage] = []
        for message in messages:
            if isinstance(message, ArtifactRefMessage) and message.content_type == ArtifactContentType.VISUALIZATION:
                content = contents_by_id.get(message.id or "")
                if content:
                    result.append(self._to_visualization_artifact_message(message, content))
            elif not isinstance(message, VisualizationMessage) and not artifacts_only:
                # Pass through non-artifact messages, but skip VisualizationMessage (they are already filtered in the state, just a precaution)
                result.append(message)

        return result

    async def aget_conversation_artifact_messages(self) -> list[ArtifactMessage]:
        """Get all artifacts created in a conversation, by the agent and subagents."""
        conversation_id = cast(UUID, self._get_thread_id(self._config))
        artifacts = list(AgentArtifact.objects.filter(team=self._team, conversation_id=conversation_id).all())
        return [
            ArtifactMessage(
                id=artifact.short_id,
                artifact_id=artifact.short_id,
                source=ArtifactSource.ARTIFACT,
                content=VisualizationArtifactContent.model_validate(artifact.data),
            )
            for artifact in artifacts
        ]

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
                        plan=msg.plan,
                    )
                except ValidationError as e:
                    capture_exception(e)
                    # Old unsupported visualization messages schemas
                    return None
        return None

    def _to_visualization_artifact_message(
        self, message: ArtifactRefMessage, content: VisualizationArtifactContent
    ) -> ArtifactMessage:
        """Convert an ArtifactRefMessage to an ArtifactMessage."""
        return ArtifactMessage(
            id=message.id,
            artifact_id=message.artifact_id,
            source=message.source,
            content=content,
        )

    async def _afetch_artifact_contents(self, artifact_ids: list[str]) -> dict[str, VisualizationArtifactContent]:
        """Batch fetch artifact contents from the database."""
        if not artifact_ids:
            return {}
        artifacts = AgentArtifact.objects.filter(short_id__in=artifact_ids, team=self._team)
        return {
            artifact.short_id: VisualizationArtifactContent.model_validate(artifact.data)
            async for artifact in artifacts
            if artifact.type == AgentArtifact.Type.VISUALIZATION
        }

    async def _afetch_insight_contents(self, insight_ids: list[str]) -> dict[str, VisualizationArtifactContent]:
        """Batch fetch insight contents from the database."""
        results = await self._afetch_insights_with_models(insight_ids)
        return {short_id: content for short_id, (content, _) in results.items()}

    async def _afetch_insights_with_models(
        self, insight_ids: list[str]
    ) -> dict[str, tuple[VisualizationArtifactContent, Insight]]:
        """Batch fetch insight contents and models from the database."""
        if not insight_ids:
            return {}
        insights = Insight.objects.filter(short_id__in=insight_ids, team=self._team, deleted=False, saved=True)
        result: dict[str, tuple[VisualizationArtifactContent, Insight]] = {}
        async for insight in insights:
            # Validate and convert dict to model
            query_obj = InsightContext.extract_query(insight)
            if query_obj is None:
                continue
            content = VisualizationArtifactContent(
                query=query_obj,
                name=insight.name or insight.derived_name,
                description=insight.description,
            )
            result[insight.short_id] = (content, insight)
        return result
