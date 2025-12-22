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
    ErrorTrackingFiltersArtifactContent,
    ErrorTrackingImpactArtifactContent,
    VisualizationArtifactContent,
    VisualizationMessage,
)

from posthog.models import Insight, User
from posthog.models.team import Team

from ee.hogai.core.mixins import AssistantContextMixin
from ee.hogai.utils.query import validate_assistant_query
from ee.hogai.utils.types.base import ArtifactRefMessage, AssistantMessageUnion
from ee.models.assistant import AgentArtifact

ArtifactContentUnion = (
    DocumentArtifactContent
    | ErrorTrackingFiltersArtifactContent
    | ErrorTrackingImpactArtifactContent
    | VisualizationArtifactContent
)

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

    async def create_error_tracking_filters(
        self,
        content: ErrorTrackingFiltersArtifactContent,
        name: str,
    ) -> AgentArtifact:
        """Create and persist an Error Tracking filters artifact."""
        if not self._config:
            raise ValueError("Config is required")

        conversation = await self._aget_conversation(cast(UUID, self._get_thread_id(self._config)))

        if conversation is None:
            raise ValueError("Conversation not found")

        artifact = AgentArtifact(
            name=name[:400],
            type=AgentArtifact.Type.ERROR_TRACKING_FILTERS,
            data=content.model_dump(exclude_none=True),
            conversation=conversation,
            team=self._team,
        )
        await artifact.asave()

        return artifact

    async def create_error_tracking_impact(
        self,
        content: ErrorTrackingImpactArtifactContent,
        name: str,
    ) -> AgentArtifact:
        """Create and persist an Error Tracking impact artifact."""
        if not self._config:
            raise ValueError("Config is required")

        conversation = await self._aget_conversation(cast(UUID, self._get_thread_id(self._config)))

        if conversation is None:
            raise ValueError("Conversation not found")

        artifact = AgentArtifact(
            name=name[:400],
            type=AgentArtifact.Type.ERROR_TRACKING_IMPACT,
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
        return cast(VisualizationArtifactContent, content)

    async def aget_error_tracking_filters_content_by_short_id(
        self, short_id: str
    ) -> ErrorTrackingFiltersArtifactContent:
        """Retrieve Error Tracking filters content from an artifact by short_id."""
        contents = await self._afetch_artifact_contents([short_id])
        content = contents.get(short_id)
        if content is None:
            raise AgentArtifact.DoesNotExist(f"Artifact with short_id={short_id} not found")
        return cast(ErrorTrackingFiltersArtifactContent, content)

    async def aget_error_tracking_filters(
        self,
        state_messages: Sequence[AssistantMessageUnion],
        artifact_id: str,
    ) -> tuple[ErrorTrackingFiltersArtifactContent, ArtifactSource] | None:
        """
        Retrieve Error Tracking filters either from a persisted artifact (short_id) or from state via an ArtifactRefMessage.
        """
        try:
            content = await self.aget_error_tracking_filters_content_by_short_id(artifact_id)
            return content, ArtifactSource.ARTIFACT
        except AgentArtifact.DoesNotExist:
            pass

        for msg in state_messages:
            if isinstance(msg, ArtifactRefMessage) and msg.id == artifact_id:
                if msg.content_type == ArtifactContentType.ERROR_TRACKING_FILTERS:
                    if msg.source == ArtifactSource.ARTIFACT:
                        try:
                            content = await self.aget_error_tracking_filters_content_by_short_id(msg.artifact_id)
                            return content, ArtifactSource.ARTIFACT
                        except AgentArtifact.DoesNotExist:
                            return None
                    return None

        return None

    async def aget_insight_with_source(
        self, state_messages: Sequence[AssistantMessageUnion], artifact_id: str
    ) -> (
        StateArtifactResult[VisualizationArtifactContent]
        | DatabaseArtifactResult[VisualizationArtifactContent]
        | ModelArtifactResult[VisualizationArtifactContent, Literal[ArtifactSource.INSIGHT], Insight]
        | None
    ):
        """
        Retrieve artifact content by ID along with its source.
        Checks state first, then artifacts, then insights.
        Returns content or None if not found.
        """
        # Try state first if messages provided
        if state_messages is not None:
            state_content = self._content_from_state(artifact_id, state_messages)
            if state_content is not None:
                return StateArtifactResult(content=state_content)

        # Fall back to database (artifact, then insight)
        artifact_contents = await self._afetch_artifact_contents([artifact_id])
        artifact_content = artifact_contents.get(artifact_id)
        if artifact_content is not None and isinstance(artifact_content, VisualizationArtifactContent):
            return DatabaseArtifactResult(content=artifact_content)

        try:
            insight = await Insight.objects.aget(short_id=artifact_id, team=self._team, deleted=False, saved=True)
            return ModelArtifactResult(
                source=ArtifactSource.INSIGHT,
                content=VisualizationArtifactContent(
                    query=insight.query, name=insight.name or insight.derived_name, description=insight.description
                ),
                model=insight,
            )
        except Insight.DoesNotExist:
            pass

        return None

    async def aget_enriched_message(
        self,
        message: ArtifactRefMessage,
        state_messages: Sequence[AssistantMessageUnion] | None = None,
    ) -> ArtifactMessage | None:
        """
        Convert an artifact message to an enriched artifact message.
        Fetches content based on source: State (from messages), Artifact (from DB), Insight (from DB), or ErrorTrackingIssue (from DB).
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

        if message.content_type == ArtifactContentType.ERROR_TRACKING_FILTERS:
            return self._to_error_tracking_filters_artifact_message(
                message, cast(ErrorTrackingFiltersArtifactContent, content)
            )

        if message.content_type == ArtifactContentType.ERROR_TRACKING_IMPACT:
            return self._to_error_tracking_impact_artifact_message(
                message, cast(ErrorTrackingImpactArtifactContent, content)
            )

        return self._to_visualization_artifact_message(message, cast(VisualizationArtifactContent, content))

    async def aget_contents_by_message_id(
        self, messages: Sequence[AssistantMessageUnion]
    ) -> dict[
        str, VisualizationArtifactContent | ErrorTrackingFiltersArtifactContent | ErrorTrackingImpactArtifactContent
    ]:
        """
        Get artifact content for all artifact messages, keyed by message ID.
        """
        result: dict[
            str, VisualizationArtifactContent | ErrorTrackingFiltersArtifactContent | ErrorTrackingImpactArtifactContent
        ] = {}

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
                state_content = self._content_from_state(message.artifact_id, messages)
                if state_content:
                    result[message.id] = state_content
            elif message.source == ArtifactSource.ARTIFACT:
                artifact_ids.append(message.artifact_id)
                artifact_id_to_message_id[message.artifact_id] = message.id
            elif message.source == ArtifactSource.INSIGHT:
                insight_ids.append(message.artifact_id)
                insight_id_to_message_id[message.artifact_id] = message.id

        # Batch fetch from DB
        artifact_contents = await self._afetch_artifact_contents(artifact_ids)
        insight_contents = await self._afetch_insight_contents(insight_ids)

        for artifact_id, artifact_content in artifact_contents.items():
            if message_id := artifact_id_to_message_id.get(artifact_id):
                result[message_id] = artifact_content
        for insight_id, insight_content in insight_contents.items():
            if message_id := insight_id_to_message_id.get(insight_id):
                result[message_id] = insight_content

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
            if isinstance(message, ArtifactRefMessage):
                content = contents_by_id.get(message.id or "")
                if content:
                    if message.content_type == ArtifactContentType.ERROR_TRACKING_FILTERS and isinstance(
                        content, ErrorTrackingFiltersArtifactContent
                    ):
                        result.append(self._to_error_tracking_filters_artifact_message(message, content))
                    elif message.content_type == ArtifactContentType.ERROR_TRACKING_IMPACT and isinstance(
                        content, ErrorTrackingImpactArtifactContent
                    ):
                        result.append(self._to_error_tracking_impact_artifact_message(message, content))
                    elif message.content_type == ArtifactContentType.VISUALIZATION and isinstance(
                        content, VisualizationArtifactContent
                    ):
                        result.append(self._to_visualization_artifact_message(message, content))
                continue
            if not isinstance(message, VisualizationMessage) and not artifacts_only:
                # Pass through non-artifact messages, but skip VisualizationMessage (they are already filtered in the state, just a precaution)
                result.append(message)

        return result

    async def aget_conversation_artifact_messages(self) -> list[ArtifactMessage]:
        """Get all artifacts created in a conversation, by the agent and subagents."""
        conversation_id = cast(UUID, self._get_thread_id(self._config))
        artifacts = list(AgentArtifact.objects.filter(team=self._team, conversation_id=conversation_id).all())
        result: list[ArtifactMessage] = []
        for artifact in artifacts:
            content = self._validate_artifact_content(artifact)
            if content is not None:
                result.append(
                    ArtifactMessage(
                        id=artifact.short_id,
                        artifact_id=artifact.short_id,
                        source=ArtifactSource.ARTIFACT,
                        content=content,
                    )
                )
        return result

    def _validate_artifact_content(self, artifact: AgentArtifact) -> ArtifactContentUnion | None:
        """Validate artifact data based on its type, returning the appropriate content model."""
        try:
            if artifact.type == AgentArtifact.Type.VISUALIZATION:
                return VisualizationArtifactContent.model_validate(artifact.data)
            elif artifact.type == AgentArtifact.Type.ERROR_TRACKING_FILTERS:
                return ErrorTrackingFiltersArtifactContent.model_validate(artifact.data)
            elif artifact.type == AgentArtifact.Type.ERROR_TRACKING_IMPACT:
                return ErrorTrackingImpactArtifactContent.model_validate(artifact.data)
            elif artifact.type == AgentArtifact.Type.NOTEBOOK:
                return DocumentArtifactContent.model_validate(artifact.data)
            else:
                capture_exception(ValueError(f"Unknown artifact type: {artifact.type}"))
                return None
        except ValidationError as e:
            capture_exception(e)
            return None

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

    def _to_error_tracking_filters_artifact_message(
        self, message: ArtifactRefMessage, content: ErrorTrackingFiltersArtifactContent
    ) -> ArtifactMessage:
        """Convert an ArtifactRefMessage to an Error Tracking filters ArtifactMessage."""
        return ArtifactMessage(
            id=message.id,
            artifact_id=message.artifact_id,
            source=message.source,
            content=content,
        )

    def _to_error_tracking_impact_artifact_message(
        self, message: ArtifactRefMessage, content: ErrorTrackingImpactArtifactContent
    ) -> ArtifactMessage:
        """Convert an ArtifactRefMessage to an Error Tracking impact ArtifactMessage."""
        return ArtifactMessage(
            id=message.id,
            artifact_id=message.artifact_id,
            source=message.source,
            content=content,
        )

    async def _afetch_artifact_contents(
        self, artifact_ids: list[str]
    ) -> dict[
        str, VisualizationArtifactContent | ErrorTrackingFiltersArtifactContent | ErrorTrackingImpactArtifactContent
    ]:
        """Batch fetch artifact contents from the database."""
        if not artifact_ids:
            return {}
        artifacts = AgentArtifact.objects.filter(short_id__in=artifact_ids, team=self._team)
        result: dict[
            str, VisualizationArtifactContent | ErrorTrackingFiltersArtifactContent | ErrorTrackingImpactArtifactContent
        ] = {}
        async for artifact in artifacts:
            if artifact.type == AgentArtifact.Type.VISUALIZATION:
                result[artifact.short_id] = VisualizationArtifactContent.model_validate(artifact.data)
            elif artifact.type == AgentArtifact.Type.ERROR_TRACKING_FILTERS:
                result[artifact.short_id] = ErrorTrackingFiltersArtifactContent.model_validate(artifact.data)
            elif artifact.type == AgentArtifact.Type.ERROR_TRACKING_IMPACT:
                result[artifact.short_id] = ErrorTrackingImpactArtifactContent.model_validate(artifact.data)
        return result

    async def _afetch_insight_contents(self, insight_ids: list[str]) -> dict[str, VisualizationArtifactContent]:
        """Batch fetch insight contents from the database."""
        if not insight_ids:
            return {}
        insights = Insight.objects.filter(short_id__in=insight_ids, team=self._team, deleted=False, saved=True)
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
            try:
                query_obj = validate_assistant_query(query)
                result[insight.short_id] = VisualizationArtifactContent(
                    query=query_obj,
                    name=insight.name or insight.derived_name,
                    description=insight.description,
                )
            except Exception as e:
                capture_exception(e)
                continue
        return result
