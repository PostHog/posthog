from enum import Enum

from ee.hogai.artifacts.manager import ArtifactManager
from ee.hogai.artifacts.types import StoredNotebookArtifactContent
from ee.hogai.tools.create_notebook.parsing import parse_notebook_content_for_storage
from ee.models.assistant import AgentArtifact


class ArtifactStatus(Enum):
    CREATED = "created"
    UPDATED = "updated"
    FAILED_TO_UPDATE = "failed_to_update"


async def create_or_update_notebook_artifact(
    artifacts_manager: ArtifactManager,
    content: str,
    title: str,
    artifact_id: str | None = None,
) -> tuple[AgentArtifact, ArtifactStatus]:
    """
    Parse markdown content and create or update a notebook artifact.

    Args:
        artifacts_manager: The ArtifactManager instance to use for persistence
        content: Markdown content with optional <insight>artifact_id</insight> tags
        title: Title for the notebook artifact
        artifact_id: Optional ID of existing artifact to update

    Returns:
        tuple[AgentArtifact, ArtifactStatus] with the artifact and status
    """
    blocks = parse_notebook_content_for_storage(content)
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

    return artifact, status
