from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

from posthoganalytics import capture_exception
from pydantic import ValidationError

from posthog.schema import ArtifactContentType, ArtifactSource, VisualizationArtifactContent, VisualizationMessage

from posthog.models import Insight, Team

from ee.hogai.artifacts.handlers.base import ArtifactHandler, EnrichmentContext, register_handler
from ee.hogai.artifacts.types import (
    DatabaseArtifactResult,
    ModelArtifactResult,
    StateArtifactResult,
    VisualizationWithSourceResult,
)
from ee.hogai.context.insight.context import InsightContext
from ee.hogai.utils.types.base import AssistantMessageUnion
from ee.models.assistant import AgentArtifact


@register_handler
class VisualizationHandler(ArtifactHandler[VisualizationArtifactContent, VisualizationArtifactContent]):
    """
    Handler for visualization artifacts.

    Visualizations can come from three sources:
    - STATE: In-memory VisualizationMessage in conversation state
    - ARTIFACT: Saved in AgentArtifact table
    - INSIGHT: Saved as Insight model

    No enrichment needed - stored content is already in final form.
    """

    content_class = VisualizationArtifactContent
    enriched_class = VisualizationArtifactContent  # Same, no enrichment
    db_type = AgentArtifact.Type.VISUALIZATION
    content_type = ArtifactContentType.VISUALIZATION

    async def alist(
        self,
        team: Team,
        ids: list[str],
        state_messages: Sequence[AssistantMessageUnion] | None = None,
    ) -> list[VisualizationWithSourceResult | None]:
        """
        Fetch visualizations with source tracking and Insight models.

        Returns ordered list matching input IDs (None for missing IDs).
        """
        if not ids:
            return []

        results_map: dict[str, VisualizationWithSourceResult] = {}
        remaining = set(ids)

        # 1. Check state messages first
        if state_messages:
            for artifact_id in list(remaining):
                content = self._from_state(artifact_id, state_messages)
                if content is not None:
                    results_map[artifact_id] = StateArtifactResult(content=content)
                    remaining.discard(artifact_id)

        # 2. Check artifact DB
        if remaining:
            db_contents = await self._from_db(list(remaining), team)
            for artifact_id, content in db_contents.items():
                results_map[artifact_id] = DatabaseArtifactResult(content=content)
                remaining.discard(artifact_id)

        # 3. Check insights table - get both content AND model in single query
        if remaining:
            insight_results = await self._from_insights_with_models(list(remaining), team)
            for artifact_id, (content, model) in insight_results.items():
                results_map[artifact_id] = ModelArtifactResult(
                    source=ArtifactSource.INSIGHT,
                    content=content,
                    model=model,
                )

        # Return ordered list matching input
        return [results_map.get(artifact_id) for artifact_id in ids]

    async def aenrich(
        self,
        content: VisualizationArtifactContent,
        context: EnrichmentContext,
    ) -> VisualizationArtifactContent:
        """No enrichment needed for visualizations."""
        return content

    def get_metadata(self, content: VisualizationArtifactContent) -> dict[str, Any]:
        return {
            "name": content.name,
            "description": content.description,
        }

    def _from_state(
        self, artifact_id: str, messages: Sequence[AssistantMessageUnion]
    ) -> VisualizationArtifactContent | None:
        """
        Extract content from a VisualizationMessage in state.

        Field mappings from VisualizationMessage to VisualizationArtifactContent:
        - answer -> query: The actual query object (e.g., TrendsQuery)
        - query -> name: The user's original query text (used as chart title)
        - plan -> description: The agent's plan/explanation
        """
        for msg in messages:
            if isinstance(msg, VisualizationMessage) and msg.id == artifact_id:
                try:
                    return VisualizationArtifactContent(query=msg.answer, name="Insight", plan=msg.plan)
                except ValidationError as e:
                    capture_exception(e)
                    # Old unsupported visualization messages schemas
                    return None
        return None

    async def _from_db(self, artifact_ids: list[str], team: Team) -> dict[str, VisualizationArtifactContent]:
        """Fetch visualization contents from AgentArtifact table."""
        if not artifact_ids:
            return {}

        artifacts = AgentArtifact.objects.filter(
            short_id__in=artifact_ids,
            team=team,
            type=AgentArtifact.Type.VISUALIZATION,
        )
        result: dict[str, VisualizationArtifactContent] = {}
        async for artifact in artifacts:
            try:
                result[artifact.short_id] = VisualizationArtifactContent.model_validate(artifact.data)
            except ValidationError:
                # Skip invalid data
                continue
        return result

    async def _from_insights_with_models(
        self, insight_ids: list[str], team: Team
    ) -> dict[str, tuple[VisualizationArtifactContent, Insight]]:
        """Fetch visualization contents along with their Insight models (single query)."""
        if not insight_ids:
            return {}

        insights = Insight.objects.filter(
            short_id__in=insight_ids,
            team=team,
            deleted=False,
            saved=True,
        )
        result: dict[str, tuple[VisualizationArtifactContent, Insight]] = {}
        async for insight in insights:
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


class VisualizationArtifactManagerMixin:
    """
    Mixin providing visualization-specific artifact retrieval methods.

    Mix into ArtifactManager to add type-safe visualization fetching.
    """

    # These are provided by ArtifactManager
    _team: Team

    async def aget_visualizations(
        self,
        state_messages: Sequence[AssistantMessageUnion],
        artifact_ids: list[str],
    ) -> list[VisualizationWithSourceResult | None]:
        """
        Fetch visualizations by IDs.

        Checks sources in priority order: STATE, ARTIFACT, INSIGHT.
        Returns ordered list matching input artifact_ids (None for missing IDs).
        """
        if not artifact_ids:
            return []
        handler = VisualizationHandler()
        return cast(
            list[VisualizationWithSourceResult | None],
            await handler.alist(self._team, artifact_ids, state_messages),
        )

    async def aget_visualization(
        self,
        state_messages: Sequence[AssistantMessageUnion],
        artifact_id: str,
    ) -> VisualizationWithSourceResult | None:
        """
        Fetch a single visualization by ID.

        Checks sources in priority order: STATE, ARTIFACT, INSIGHT.
        """
        results = await self.aget_visualizations(state_messages, [artifact_id])
        return results[0] if results else None
