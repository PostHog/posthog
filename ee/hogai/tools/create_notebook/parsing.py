import re

from posthog.schema import LoadingBlock, MarkdownBlock

from ee.hogai.artifacts.manager import StoredBlock, VisualizationRefBlock

# Regex pattern to find <insight>artifact_id</insight> tags
INSIGHT_TAG_PATTERN = r"<insight>([^<]+)</insight>"


def parse_notebook_content_for_storage(content: str) -> list[StoredBlock]:
    """
    Parse markdown content into StoredBlock[] for persistence.

    Creates VisualizationRefBlock with just artifact_id references.
    These will be enriched to full VisualizationBlock when streaming to the client.

    Args:
        content: Markdown content with optional <insight>artifact_id</insight> tags

    Returns:
        List of StoredBlock (MarkdownBlock, VisualizationRefBlock, SessionReplayBlock)
    """
    blocks: list[StoredBlock] = []

    last_end = 0
    for match in re.finditer(INSIGHT_TAG_PATTERN, content):
        # Add markdown block for text before the tag
        if match.start() > last_end:
            text = content[last_end : match.start()].strip()
            if text:
                blocks.append(MarkdownBlock(content=text))

        # Add visualization reference block (just the artifact_id)
        artifact_id = match.group(1).strip()
        blocks.append(VisualizationRefBlock(artifact_id=artifact_id))

        last_end = match.end()

    # Add remaining text as markdown block
    if last_end < len(content):
        text = content[last_end:].strip()
        if text:
            blocks.append(MarkdownBlock(content=text))

    # If no blocks were created (no content), add an empty markdown block
    if not blocks:
        blocks.append(MarkdownBlock(content=""))

    return blocks


def parse_notebook_content_for_streaming(
    content: str,
    strip_incomplete_tags: bool = True,
) -> list[StoredBlock]:
    """
    Parse markdown content into StoredBlock[] for streaming.

    Creates LoadingBlock placeholders for <insight> tags that are still being streamed.
    Uses strip_incomplete_tags to handle partial tags during streaming.

    Args:
        content: Markdown content with optional <insight>artifact_id</insight> tags
        strip_incomplete_tags: If True, strips incomplete insight tags at the end

    Returns:
        List of StoredBlock with LoadingBlock placeholders
    """
    blocks: list[StoredBlock] = []

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

        # Add loading block placeholder
        artifact_id = match.group(1).strip()
        blocks.append(LoadingBlock(artifact_id=artifact_id))

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
