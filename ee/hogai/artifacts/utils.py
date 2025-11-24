from typing import Any, TypeGuard

from posthog.schema import ArtifactContentType, ArtifactMessage, VisualizationMessage


def is_visualization_artifact_message(message: Any) -> TypeGuard[ArtifactMessage]:
    return isinstance(message, ArtifactMessage) and message.content_type == ArtifactContentType.VISUALIZATION


def is_visualization(message: Any) -> TypeGuard[VisualizationMessage | ArtifactMessage]:
    return isinstance(message, VisualizationMessage) or is_visualization_artifact_message(message)
