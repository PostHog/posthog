from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

from pydantic import ValidationError

from posthog.schema import ArtifactContentType, ErrorBlock, NotebookArtifactContent, VisualizationBlock

from posthog.models import Team

from ee.hogai.artifacts.handlers.base import (
    ArtifactHandler,
    EnrichmentContext,
    get_handler_for_content_type,
    register_handler,
)
from ee.hogai.artifacts.types import (
    DatabaseArtifactResult,
    EnrichedBlock,
    NotebookWithSourceResult,
    StoredNotebookArtifactContent,
    VisualizationRefBlock,
)
from ee.hogai.context.insight.query_executor import is_supported_query
from ee.hogai.utils.types.base import AssistantMessageUnion
from ee.models.assistant import AgentArtifact


@register_handler
class NotebookHandler(ArtifactHandler[StoredNotebookArtifactContent, NotebookArtifactContent]):
    """
    Handler for notebook artifacts.

    Notebooks are only stored in the ARTIFACT source (AgentArtifact table).
    They contain VisualizationRefBlock references that need to be enriched
    to full VisualizationBlock content when streaming.
    """

    content_class = StoredNotebookArtifactContent
    enriched_class = NotebookArtifactContent
    db_type = AgentArtifact.Type.NOTEBOOK
    content_type = ArtifactContentType.NOTEBOOK

    async def alist(
        self,
        team: Team,
        ids: list[str],
        state_messages: Sequence[AssistantMessageUnion] | None = None,
    ) -> list[NotebookWithSourceResult | None]:
        """
        Fetch notebook content by IDs from AgentArtifact table.

        Returns ordered list matching input IDs (None for missing artifacts).
        """
        if not ids:
            return []

        artifacts = AgentArtifact.objects.filter(
            short_id__in=ids,
            team=team,
            type=AgentArtifact.Type.NOTEBOOK,
        )
        result: dict[str, NotebookWithSourceResult] = {}
        async for artifact in artifacts:
            try:
                content = StoredNotebookArtifactContent.model_validate(artifact.data)
                result[artifact.short_id] = DatabaseArtifactResult(content=content)
            except ValidationError:
                # Skip invalid data
                continue
        return [result.get(artifact_id) for artifact_id in ids]

    async def aenrich(
        self,
        content: StoredNotebookArtifactContent,
        context: EnrichmentContext,
    ) -> NotebookArtifactContent:
        """
        Enrich notebook by resolving VisualizationRefBlock references.

        Converts VisualizationRefBlock → VisualizationBlock (with full query data)
        or ErrorBlock (if artifact not found).
        """
        # Collect all artifact IDs from VisualizationRefBlock
        viz_ids = [block.artifact_id for block in content.blocks if isinstance(block, VisualizationRefBlock)]

        # Fetch visualization contents using the visualization handler
        viz_contents = await self._list_visualization_contents(viz_ids, context.team, context.state_messages)

        # Build enriched blocks
        enriched_blocks: list[EnrichedBlock] = []
        for block in content.blocks:
            if isinstance(block, VisualizationRefBlock):
                viz_content = viz_contents.get(block.artifact_id)
                if viz_content is None:
                    # Artifact not found - generate error block
                    enriched_blocks.append(
                        ErrorBlock(
                            message=f"Visualization not found: {block.artifact_id}",
                            artifact_id=block.artifact_id,
                        )
                    )
                elif not is_supported_query(viz_content.query):
                    # Query type not supported for rendering
                    enriched_blocks.append(
                        ErrorBlock(
                            message=f"Unsupported query type: {type(viz_content.query).__name__}",
                            artifact_id=block.artifact_id,
                        )
                    )
                else:
                    # Valid visualization - cast is safe now after runtime validation
                    enriched_blocks.append(
                        VisualizationBlock(
                            query=cast(Any, viz_content.query),
                            title=block.title or viz_content.name,
                        )
                    )
            else:
                # Pass through other block types unchanged
                enriched_blocks.append(block)

        return NotebookArtifactContent(
            blocks=enriched_blocks,
            title=content.title,
        )

    def get_metadata(self, content: StoredNotebookArtifactContent) -> dict[str, Any]:
        return {
            "title": content.title,
        }

    async def _list_visualization_contents(
        self,
        artifact_ids: list[str],
        team: Team,
        state_messages: Sequence[AssistantMessageUnion] | None = None,
    ):
        """
        Fetch visualization contents for ref block artifact IDs.

        Uses the VisualizationHandler (via registry) to handle fetching from all sources.
        Returns dict mapping artifact_id -> content for easy lookup during enrichment.
        """
        if not artifact_ids:
            return {}

        viz_handler = get_handler_for_content_type(ArtifactContentType.VISUALIZATION)
        if viz_handler is None:
            return {}

        # list returns result wrappers, extract content for lookup
        results = await viz_handler.alist(team, artifact_ids, state_messages)
        return {artifact_id: result.content for artifact_id, result in zip(artifact_ids, results) if result is not None}


class NotebookArtifactManagerMixin:
    """
    Mixin providing notebook-specific artifact retrieval methods.

    Mix into ArtifactManager to add type-safe notebook fetching.
    """

    # These are provided by ArtifactManager
    _team: Team

    async def aget_notebooks(
        self,
        state_messages: Sequence[AssistantMessageUnion],
        artifact_ids: list[str],
    ) -> list[NotebookWithSourceResult | None]:
        """
        Fetch notebooks by IDs.

        Notebooks are only stored in the ARTIFACT source.
        Returns ordered list matching input artifact_ids (None for missing IDs).
        """
        if not artifact_ids:
            return []
        handler = NotebookHandler()
        return cast(
            list[NotebookWithSourceResult | None],
            await handler.alist(self._team, artifact_ids, state_messages),
        )

    async def aget_notebook(
        self,
        state_messages: Sequence[AssistantMessageUnion],
        artifact_id: str,
    ) -> NotebookWithSourceResult | None:
        """
        Fetch a single notebook by ID.
        """
        results = await self.aget_notebooks(state_messages, [artifact_id])
        return results[0] if results else None
