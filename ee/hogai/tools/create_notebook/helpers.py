from collections.abc import Sequence
from enum import Enum

from posthog.models import Team, User
from posthog.rbac.user_access_control import UserAccessControl

from products.notebooks.backend.models import Notebook
from products.posthog_ai.backend.models.assistant import AgentArtifact

from ee.hogai.artifacts.handlers.visualization import VisualizationHandler
from ee.hogai.artifacts.manager import ArtifactManager
from ee.hogai.artifacts.types import (
    ModelArtifactResult,
    StoredBlock,
    StoredNotebookArtifactContent,
    VisualizationRefBlock,
)
from ee.hogai.tools.create_notebook.parsing import parse_notebook_content_for_storage
from ee.hogai.tools.create_notebook.tiptap import blocks_to_tiptap_doc
from ee.hogai.utils.types.base import AssistantMessageUnion


class ArtifactStatus(Enum):
    CREATED = "created"
    UPDATED = "updated"
    FAILED_TO_UPDATE = "failed_to_update"


async def create_or_update_notebook_artifact(
    artifacts_manager: ArtifactManager,
    content: str,
    title: str,
    artifact_id: str | None = None,
) -> tuple[AgentArtifact, ArtifactStatus, list[StoredBlock]]:
    """
    Parse markdown content and create or update a notebook artifact.

    Returns:
        tuple of (artifact, status, parsed_blocks)
    """
    blocks = parse_notebook_content_for_storage(content, title=title)
    artifact_content = StoredNotebookArtifactContent(blocks=blocks, title=title)

    artifact = None
    status = ArtifactStatus.CREATED

    if artifact_id:
        try:
            artifact = await artifacts_manager.aupdate(artifact_id, artifact_content)
            status = ArtifactStatus.UPDATED
        except ValueError:
            status = ArtifactStatus.FAILED_TO_UPDATE

    if not artifact:
        artifact = await artifacts_manager.acreate(content=artifact_content, name=title)
        if status != ArtifactStatus.FAILED_TO_UPDATE:
            status = ArtifactStatus.CREATED

    return artifact, status, blocks


async def save_notebook_to_db(
    team: Team,
    user: User,
    artifact: AgentArtifact,
    blocks: Sequence[StoredBlock],
    title: str,
    state_messages: Sequence[AssistantMessageUnion],
) -> Notebook:
    """
    Save or update a real Notebook record with the same short_id as the artifact.

    If a Notebook with the artifact's short_id already exists, update its content.
    Otherwise, create a new Notebook.
    """
    # Resolve viz refs through the unified handler (state → AgentArtifact → Insight),
    # matching the chat preview. A direct AgentArtifact query misses state-only charts.
    ref_ids = [block.artifact_id for block in blocks if isinstance(block, VisualizationRefBlock)]
    viz_lookup: dict[str, dict] = {}
    if ref_ids:
        viz_handler = VisualizationHandler()
        user_access_control = UserAccessControl(user, team)
        results = await viz_handler.alist(team, ref_ids, state_messages)
        for ref_id, result in zip(ref_ids, results):
            if result is None or result.content.query is None:
                continue
            if isinstance(result, ModelArtifactResult) and not user_access_control.check_access_level_for_object(
                result.model, "viewer"
            ):
                continue
            query = result.content.query.model_dump(mode="json", exclude_none=True)
            kind = query.get("kind", "")
            if kind == "DataVisualizationNode":
                # Already a top-level SQL chart node, do not double-wrap.
                notebook_query = query
            elif kind == "HogQLQuery" or "HogQL" in kind:
                notebook_query = {"kind": "DataVisualizationNode", "source": query}
            else:
                notebook_query = {"kind": "InsightVizNode", "source": query}
            viz_lookup[ref_id] = {"query": notebook_query, "name": result.content.name}

    def resolve_visualization(artifact_id: str) -> dict | None:
        return viz_lookup.get(artifact_id)

    tiptap_doc = blocks_to_tiptap_doc(blocks, title=title, resolve_visualization=resolve_visualization)

    notebook, created = await Notebook.objects.aget_or_create(
        team=team,
        short_id=artifact.short_id,
        defaults={
            "created_by": user,
            "last_modified_by": user,
            "title": title,
            "content": tiptap_doc,
        },
    )
    if not created:
        notebook.content = tiptap_doc
        notebook.title = title
        notebook.last_modified_by = user
        await notebook.asave(update_fields=["content", "title", "last_modified_by", "last_modified_at"])

    return notebook


async def notebook_exists_for_artifact(team: Team, short_id: str) -> bool:
    return await Notebook.objects.filter(team=team, short_id=short_id).aexists()
