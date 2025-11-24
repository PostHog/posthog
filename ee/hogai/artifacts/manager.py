from typing import cast
from uuid import UUID, uuid4

from langchain_core.runnables import RunnableConfig

from posthog.schema import (
    ArtifactContentType,
    ArtifactMessage,
    ArtifactSource,
    VisualizationArtifactContent,
    VisualizationArtifactMessage,
)

from posthog.models import Insight, User
from posthog.models.team import Team

from ee.hogai.core.mixins import AssistantContextMixin
from ee.hogai.utils.types.base import AnyAssistantSupportedQuery, AssistantMessageUnion
from ee.models.assistant import AgentArtifact


class ArtifactManager(AssistantContextMixin):
    """
    Manages creation and retrieval of agent artifacts.
    """

    def __init__(self, team: Team, user: User, config: RunnableConfig | None = None):
        self._team = team
        self._user = user
        self._config = config or {}

    def create_artifact_message(
        self,
        artifact_id: str,
        source: ArtifactSource = ArtifactSource.ARTIFACT,
        content_type: ArtifactContentType = ArtifactContentType.VISUALIZATION,
    ) -> ArtifactMessage:
        """
        Create an artifact message.

        Args:
            artifact_id: The short_id of the artifact
            source: The source of the artifact
        """
        return ArtifactMessage(
            content_type=content_type,
            artifact_id=artifact_id,
            source=source,
            id=str(uuid4()),
        )

    async def create_visualization_artifact(
        self,
        content: VisualizationArtifactContent,
        name: str,
    ) -> AgentArtifact:
        """
        Create a visualization artifact.

        Args:
            content: The visualization content (query, name, description)
            name: Display name for the artifact

        Returns:
            The created AgentArtifact
        """
        if not self._config:
            raise ValueError("Config is required")

        conversation = await self._aget_conversation(cast(UUID, self._get_thread_id(self._config)))

        artifact = AgentArtifact(
            name=name[:400],
            type=AgentArtifact.Type.VISUALIZATION,
            data=content.model_dump(),
            conversation=conversation,
            team=self._team,
        )
        await artifact.asave()

        return artifact

    async def aget_by_short_id(self, short_id: str) -> AgentArtifact:
        """
        Retrieve an artifact by short_id.

        Args:
            short_id: The short_id of the artifact

        Returns:
            The AgentArtifact
        """
        return await AgentArtifact.objects.aget(short_id=short_id, team=self._team)

    async def aget_by_short_ids(self, short_ids: list[str]) -> dict[str, AgentArtifact]:
        """
        Batch fetch artifacts by short_ids.

        Args:
            short_ids: List of short_ids to fetch

        Returns:
            Dict mapping short_id to AgentArtifact
        """
        if not short_ids:
            return {}

        artifacts = AgentArtifact.objects.filter(short_id__in=short_ids, team=self._team)
        return {artifact.short_id: artifact async for artifact in artifacts}

    def get_from_messages(
        self, messages: list[AssistantMessageUnion], filter_by_type: AgentArtifact.Type | None = None
    ) -> list[AgentArtifact]:
        """
        Retrieve artifacts from messages.

        Note: This method is intentionally synchronous as it's only called from
        synchronous contexts. If you need to call this from async code, consider
        adding an async variant (aget_artifacts_from_messages).
        """
        short_ids: list[str] = [
            message.artifact_id
            for message in messages
            if isinstance(message, ArtifactMessage) and message.source == ArtifactSource.ARTIFACT
        ]
        query = AgentArtifact.objects.filter(short_id__in=short_ids, team=self._team)
        if filter_by_type:
            query = query.filter(type=filter_by_type)
        return list(query.all())

    async def aget_visualization_content_by_short_id(self, short_id: str) -> VisualizationArtifactContent:
        """
        Retrieve and validate visualization content from an artifact.

        Args:
            short_id: The short_id of the artifact

        Returns:
            The validated VisualizationArtifactContent
        """
        artifact = await self.aget_by_short_id(short_id)
        if artifact.type != AgentArtifact.Type.VISUALIZATION:
            raise ValueError(f"Expected a visualization artifact, found {artifact.type}")
        return VisualizationArtifactContent.model_validate(artifact.data)

    async def aget_visualization_content_by_insight_short_id(
        self, short_id: str
    ) -> VisualizationArtifactContent | None:
        """
        Retrieve and validate visualization content from a saved insight.

        Args:
            reference_id: The short_id of the insight

        Returns:
            The validated VisualizationArtifactContent, or None if insight doesn't exist or has no valid query
        """
        try:
            insight = await Insight.objects.aget(short_id=short_id, team=self._team)
        except Insight.DoesNotExist:
            return None

        query = insight.query

        if not query:
            return None

        # Insights store queries wrapped in InsightVizNode, extract the inner query
        if isinstance(query, dict) and query.get("kind") == "InsightVizNode":
            query = query.get("source")
            if not query:
                return None

        return VisualizationArtifactContent(
            query=cast(AnyAssistantSupportedQuery, query),
            name=insight.name or insight.derived_name,
            description=insight.description,
        )

    async def aget_visualization_artifact_message(
        self, message: ArtifactMessage
    ) -> VisualizationArtifactMessage | None:
        """
        Convert an artifact message to a visualization artifact message ready to be streamed.
        Fetches content from either draft artifact or saved insight based on source.

        Returns:
            The VisualizationArtifactMessage, or None if the artifact/insight no longer exists
        """
        if message.source == ArtifactSource.ARTIFACT:
            # Draft artifact - fetch from AgentArtifact
            content = await self.aget_visualization_content_by_short_id(message.artifact_id)
        elif message.source == ArtifactSource.INSIGHT:
            # Reference to saved insight - fetch from Insight
            maybe_content = await self.aget_visualization_content_by_insight_short_id(message.artifact_id)
            if maybe_content is None:
                return None
            content = maybe_content
        else:
            raise ValueError(f"Invalid artifact source: {message.source}")

        return VisualizationArtifactMessage(
            id=message.id,
            parent_tool_call_id=message.parent_tool_call_id,
            content_type="visualization",
            artifact_id=message.artifact_id,
            source=message.source,
            content=content,
        )

    async def aenrich_messages(self, messages: list[AssistantMessageUnion]) -> list[AssistantMessageUnion]:
        """
        Enrich state messages with artifact content.
        Returns a dict keyed by message.id with enriched messages (or None if not found).
        """
        enriched_artifact_messages: dict[str, VisualizationArtifactMessage | None] = {}

        artifact_source_messages = []
        insight_source_messages = []
        for message in messages:
            if isinstance(message, ArtifactMessage):
                if message.content_type == ArtifactContentType.VISUALIZATION:
                    if message.source == ArtifactSource.ARTIFACT:
                        artifact_source_messages.append(message)
                    elif message.source == ArtifactSource.INSIGHT:
                        insight_source_messages.append(message)

        enriched_artifact_messages.update(await self._aenrich_artifact_visualization_messages(artifact_source_messages))
        enriched_artifact_messages.update(await self._aenrich_insight_visualization_messages(insight_source_messages))

        # Build result using batch-enriched artifacts
        result: list[AssistantMessageUnion] = []
        for message in messages:
            if isinstance(message, ArtifactMessage):
                enriched = enriched_artifact_messages.get(cast(str, message.id))
                if enriched:
                    result.append(enriched)
            else:
                result.append(message)

        return result

    async def _aenrich_artifact_visualization_messages(
        self, messages: list[ArtifactMessage]
    ) -> dict[str, VisualizationArtifactMessage | None]:
        result: dict[str, VisualizationArtifactMessage | None] = {}
        draft_ids = [m.artifact_id for m in messages]
        if draft_ids:
            artifacts = await self.aget_by_short_ids(draft_ids)
            for msg in messages:
                artifact = artifacts.get(msg.artifact_id)
                if artifact:
                    content = VisualizationArtifactContent.model_validate(artifact.data)
                    result[cast(str, msg.id)] = VisualizationArtifactMessage(
                        id=msg.id,
                        parent_tool_call_id=msg.parent_tool_call_id,
                        content_type="visualization",
                        artifact_id=msg.artifact_id,
                        source=msg.source,
                        content=content,
                    )
                else:
                    result[cast(str, msg.id)] = None
        return result

    async def _aenrich_insight_visualization_messages(
        self, messages: list[ArtifactMessage]
    ) -> dict[str, VisualizationArtifactMessage | None]:
        result: dict[str, VisualizationArtifactMessage | None] = {}
        # Batch fetch saved insights
        saved_ids = [m.artifact_id for m in messages]
        if saved_ids:
            insights = {i.short_id: i async for i in Insight.objects.filter(short_id__in=saved_ids, team=self._team)}
            for msg in messages:
                insight = insights.get(msg.artifact_id)
                if insight and insight.query:
                    query = insight.query
                    # Insights store queries wrapped in InsightVizNode, extract the inner query
                    if isinstance(query, dict) and query.get("kind") == "InsightVizNode":
                        query = query.get("source")
                    if query:
                        content = VisualizationArtifactContent(
                            query=cast(AnyAssistantSupportedQuery, query),
                            name=insight.name or insight.derived_name,
                            description=insight.description,
                        )
                        result[cast(str, msg.id)] = VisualizationArtifactMessage(
                            id=msg.id,
                            parent_tool_call_id=msg.parent_tool_call_id,
                            content_type="visualization",
                            artifact_id=msg.artifact_id,
                            source=msg.source,
                            content=content,
                        )
                    else:
                        result[cast(str, msg.id)] = None
                else:
                    result[cast(str, msg.id)] = None
        return result
