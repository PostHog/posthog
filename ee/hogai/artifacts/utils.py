from typing import Any, TypeGuard

from posthog.schema import ArtifactContentType, ArtifactMessage, VisualizationArtifactContent


def is_visualization_artifact_message(message: Any) -> TypeGuard[ArtifactMessage]:
    return (
        isinstance(message, ArtifactMessage) and message.content.content_type == ArtifactContentType.VISUALIZATION.value
    )


def unwrap_visualization_artifact_content(message: Any) -> VisualizationArtifactContent | None:
    if (
        not isinstance(message, ArtifactMessage)
        or message.content.content_type != ArtifactContentType.VISUALIZATION.value
    ):
        return None
    return message.content
