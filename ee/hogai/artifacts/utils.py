from typing import Any, TypeGuard

from posthog.schema import ArtifactContentType, ArtifactMessage, NotebookArtifactContent, VisualizationArtifactContent

from ee.hogai.utils.types.base import ArtifactRefMessage


def is_visualization_artifact_message(message: Any) -> TypeGuard[ArtifactMessage | ArtifactRefMessage]:
    """Check if a message is an ArtifactMessage or ArtifactRefMessage with visualization content."""
    if isinstance(message, ArtifactMessage):
        return message.content.content_type == "visualization"
    if isinstance(message, ArtifactRefMessage):
        return message.content_type == ArtifactContentType.VISUALIZATION
    return False


def unwrap_visualization_artifact_content(message: Any) -> VisualizationArtifactContent | None:
    """Extract VisualizationArtifactContent from an ArtifactMessage, or return None."""
    if not isinstance(message, ArtifactMessage) or message.content.content_type != "visualization":
        return None
    return message.content


def unwrap_notebook_artifact_content(message: Any) -> NotebookArtifactContent | None:
    """Extract NotebookArtifactContent from an ArtifactMessage, or return None."""
    if not isinstance(message, ArtifactMessage) or message.content.content_type != "notebook":
        return None
    return message.content
