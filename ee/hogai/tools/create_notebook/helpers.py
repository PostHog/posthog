from collections.abc import Sequence
from enum import Enum
from typing import Any

from posthog.models import Team, User
from posthog.rbac.user_access_control import UserAccessControl
from posthog.sync import database_sync_to_async

from products.notebooks.backend.facade import (
    api as notebooks,
    collab,
)
from products.notebooks.backend.facade.content import (
    build_markdown_notebook_content,
    convert_notebook_content_to_markdown,
)
from products.notebooks.backend.facade.contracts import NotebookData
from products.posthog_ai.backend.models.assistant import AgentArtifact

from ee.hogai.artifacts.handlers.visualization import VisualizationHandler
from ee.hogai.artifacts.manager import ArtifactManager
from ee.hogai.artifacts.types import StoredBlock, StoredNotebookArtifactContent, VisualizationRefBlock
from ee.hogai.tools.create_notebook.parsing import parse_notebook_content_for_storage
from ee.hogai.tools.create_notebook.tiptap import blocks_to_tiptap_doc
from ee.hogai.utils.feature_flags import has_markdown_notebooks_feature_flag
from ee.hogai.utils.types.base import AssistantMessageUnion


class ArtifactStatus(Enum):
    CREATED = "created"
    UPDATED = "updated"
    FAILED_TO_UPDATE = "failed_to_update"


class NotebookEditNotAllowedError(Exception):
    """The user lacks editor access on the saved notebook this artifact would overwrite."""


MARKDOWN_NOTEBOOK_NODE_ID = "markdown-notebook-v2"
MARKDOWN_NOTEBOOK_NODE_TYPE = "ph-markdown-notebook"


def _get_markdown_notebook_node(content: Any) -> dict[str, Any] | None:
    if not isinstance(content, dict):
        return None

    nodes = content.get("content")
    if not isinstance(nodes, list) or len(nodes) != 1:
        return None

    node = nodes[0]
    if not isinstance(node, dict) or node.get("type") != MARKDOWN_NOTEBOOK_NODE_TYPE:
        return None

    return node


def _build_markdown_notebook_doc(markdown: str, existing_content: Any) -> dict[str, Any]:
    existing_node = _get_markdown_notebook_node(existing_content)
    existing_attrs = existing_node.get("attrs") if existing_node else None
    attrs: dict[str, Any] = existing_attrs.copy() if isinstance(existing_attrs, dict) else {}
    node_id = attrs.get("nodeId")
    if not isinstance(node_id, str) or not node_id:
        attrs["nodeId"] = MARKDOWN_NOTEBOOK_NODE_ID
    attrs["markdown"] = markdown

    return {
        "type": "doc",
        "content": [
            {
                "type": MARKDOWN_NOTEBOOK_NODE_TYPE,
                "attrs": attrs,
            }
        ],
    }


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
    markdown_content: str | None = None,
) -> NotebookData:
    """
    Save or update a real Notebook record with the same short_id as the artifact.

    If a Notebook with the artifact's short_id already exists, update its content.
    Otherwise, create a new Notebook.

    Raises NotebookEditNotAllowedError when a notebook exists and the user does not
    have editor access to it — Max acts on the user's behalf and must not overwrite
    notebooks the user couldn't edit themselves.
    """
    existing_notebook = await notebooks.aget_notebook(team.id, artifact.short_id, include_deleted=True)
    if existing_notebook is not None:
        access_control = UserAccessControl(user=user, team=team)
        if not await notebooks.acan_user_edit_notebook(team.id, artifact.short_id, user_access_control=access_control):
            raise NotebookEditNotAllowedError(
                f"User {user.id} does not have editor access to notebook {existing_notebook.short_id}"
            )

    if existing_notebook and markdown_content is not None and _get_markdown_notebook_node(existing_notebook.content):
        previous_content = existing_notebook.content
        next_content = _build_markdown_notebook_doc(markdown_content, previous_content)
        updated_notebook = await notebooks.aupdate_notebook_content(
            team.id,
            artifact.short_id,
            content=next_content,
            title=title,
            text_content=markdown_content,
            last_modified_by_id=user.id,
        )
        if updated_notebook is None:
            raise RuntimeError(f"Notebook {artifact.short_id} disappeared during content update")
        # The base_crc inside the diff lets receivers detect a racing concurrent edit
        # (this path has no version CAS) and fall back to a reload instead of misapplying.
        await collab.apublish_notebook_update(
            team.id,
            str(updated_notebook.short_id),
            updated_notebook.version,
            diff=collab.build_markdown_update_diff(previous_content, next_content),
        )
        return updated_notebook

    # Resolve viz refs through the unified handler (state → AgentArtifact → Insight),
    # matching the chat preview. A direct AgentArtifact query misses state-only charts.
    ref_ids = [block.artifact_id for block in blocks if isinstance(block, VisualizationRefBlock)]
    viz_lookup: dict[str, dict] = {}
    if ref_ids:
        viz_handler = VisualizationHandler()
        results = await viz_handler.alist(team, ref_ids, state_messages)
        for ref_id, result in zip(ref_ids, results):
            if result is None or result.content.query is None:
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

    # New notebooks follow the markdown notebooks rollout. Existing TipTap notebooks keep
    # their stored format so open editors don't flip formats mid-session.
    content: dict[str, Any] = tiptap_doc
    text_content: str | None = None
    if existing_notebook is None and await database_sync_to_async(has_markdown_notebooks_feature_flag)(team, user):
        markdown = convert_notebook_content_to_markdown(tiptap_doc)
        content = build_markdown_notebook_content(markdown)
        text_content = markdown

    notebook, created = await notebooks.aupsert_notebook(
        team.id,
        artifact.short_id,
        created_by_id=user.id,
        last_modified_by_id=user.id,
        title=title,
        content=content,
        text_content=text_content,
    )
    if not created:
        await collab.apublish_notebook_update(team.id, str(notebook.short_id), notebook.version)

    return notebook


async def notebook_exists_for_artifact(team: Team, short_id: str) -> bool:
    return await notebooks.anotebook_exists(team.id, short_id)
