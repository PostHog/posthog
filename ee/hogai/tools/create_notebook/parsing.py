import re
from collections.abc import Mapping

from posthog.schema import (
    ErrorBlock,
    LoadingBlock,
    MarkdownBlock,
    NotebookArtifactContent,
    SessionReplayBlock,
    VisualizationArtifactContent,
    VisualizationBlock,
)

DocumentBlock = MarkdownBlock | VisualizationBlock | SessionReplayBlock | LoadingBlock | ErrorBlock
ArtifactContent = VisualizationArtifactContent | NotebookArtifactContent

# Regex pattern to find <insight>artifact_id</insight> tags
INSIGHT_TAG_PATTERN = r"<insight>([^<]+)</insight>"


def parse_notebook_content(
    content: str,
    artifact_contents: Mapping[str, ArtifactContent] | None = None,
    strip_incomplete_tags: bool = False,
) -> list[DocumentBlock]:
    """
    Parse markdown content into DocumentBlock[].

    Args:
        content: Markdown content with optional <insight>artifact_id</insight> tags
        artifact_contents: Map of artifact_id -> VisualizationArtifactContent for resolving queries.
                          If None or artifact not found, creates placeholder VisualizationBlock.
        strip_incomplete_tags: If True, strips incomplete insight tags at the end (for streaming support)

    Returns:
        List of DocumentBlock (MarkdownBlock, VisualizationBlock, SessionReplayBlock)
    """
    blocks: list[DocumentBlock] = []

    cleaned_content = content
    if strip_incomplete_tags:
        cleaned_content = _strip_incomplete_insight_tags(content)

    last_end = 0
    for match in re.finditer(INSIGHT_TAG_PATTERN, cleaned_content):
        # Add markdown block for text before the tag
        if match.start() > last_end:
            text = cleaned_content[last_end : match.start()].strip()
            if text:
                blocks.append(MarkdownBlock(content=text))

        # Add visualization block
        artifact_id = match.group(1).strip()
        viz_content = artifact_contents.get(artifact_id) if artifact_contents else None

        if viz_content and isinstance(viz_content, VisualizationArtifactContent):
            # Resolved: use actual query data
            blocks.append(
                VisualizationBlock(
                    query=viz_content.query,
                    title=viz_content.name,
                )
            )
        elif artifact_contents is None:
            # Streaming mode: artifact_contents not provided yet, show loading block
            blocks.append(LoadingBlock(artifact_id=artifact_id))
        else:
            # Final mode: artifact_contents provided but this specific artifact wasn't found
            blocks.append(
                ErrorBlock(
                    message=f"There was an error loading this insight: {artifact_id}",
                    artifact_id=artifact_id,
                )
            )

        last_end = match.end()

    # Add remaining text as markdown block
    if last_end < len(cleaned_content):
        text = cleaned_content[last_end:].strip()
        if text:
            blocks.append(MarkdownBlock(content=text))

    # If no blocks were created (no content), add an empty markdown block
    if not blocks:
        blocks.append(MarkdownBlock(content=""))

    return blocks


def _strip_incomplete_insight_tags(content: str) -> str:
    """
    Strip incomplete insight tags at the end of content (for streaming support).
    """
    cleaned = content
    # Remove partial opening tags: <i, <in, <ins, etc.
    cleaned = re.sub(r"<i(?:n(?:s(?:i(?:g(?:h(?:t)?)?)?)?)?)?$", "", cleaned)
    # Remove <insight> tags without complete closing tag
    cleaned = re.sub(r"<insight>[^<]*$", "", cleaned)
    # Remove partial closing tags: </i, </in, etc.
    cleaned = re.sub(r"</i(?:n(?:s(?:i(?:g(?:h(?:t)?)?)?)?)?)?$", "", cleaned)
    # Remove <insight> with partial closing tag
    cleaned = re.sub(r"<insight>[^<]*</i(?:n(?:s(?:i(?:g(?:h(?:t)?)?)?)?)?)?$", "", cleaned)
    return cleaned
