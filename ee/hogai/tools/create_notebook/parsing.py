import re
from collections.abc import Callable
from typing import TypeVar

from posthog.schema import LoadingBlock, MarkdownBlock

from ee.hogai.artifacts.types import StoredBlock, VisualizationRefBlock

# Regex pattern to find <insight>artifact_id</insight> tags
INSIGHT_TAG_PATTERN = r"<insight>([^<]+)</insight>"

T = TypeVar("T", VisualizationRefBlock, LoadingBlock)


def _parse_notebook_content(
    content: str,
    create_insight_block: Callable[[str], T],
) -> list[StoredBlock]:
    """
    Common parsing logic for notebook content.

    Args:
        content: Markdown content with optional <insight>artifact_id</insight> tags
        create_insight_block: Factory function to create the appropriate block type for insight tags

    Returns:
        List of StoredBlock
    """
    blocks: list[StoredBlock] = []

    last_end = 0
    for match in re.finditer(INSIGHT_TAG_PATTERN, content):
        # Add markdown block for text before the tag
        if match.start() > last_end:
            text = content[last_end : match.start()].strip()
            if text:
                blocks.append(MarkdownBlock(content=text))

        # Add insight block using the factory
        artifact_id = match.group(1).strip()
        blocks.append(create_insight_block(artifact_id))

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


def _strip_title_heading(content: str, title: str | None) -> str:
    """
    Strip the first H1 heading from content if it matches the title.

    LLMs often generate a markdown H1 heading that duplicates the notebook title.
    This function removes that redundancy.

    Args:
        content: Markdown content
        title: The notebook title to compare against

    Returns:
        Content with duplicate H1 heading removed if it matched the title
    """
    if not title:
        return content

    # Match H1 at the start of content (with optional leading whitespace)
    h1_pattern = r"^\s*#\s+(.+?)(?:\n|$)"
    match = re.match(h1_pattern, content)

    if match:
        heading_text = match.group(1).strip()
        if heading_text.lower() == title.lower():
            # Remove the H1 heading and any following blank lines
            return content[match.end() :].lstrip("\n")

    return content


def parse_notebook_content_for_storage(content: str, title: str | None = None) -> list[StoredBlock]:
    """
    Parse markdown content into StoredBlock[] for persistence.

    Creates VisualizationRefBlock with just artifact_id references.
    These will be enriched to full VisualizationBlock when streaming to the client.

    Args:
        content: Markdown content with optional <insight>artifact_id</insight> tags
        title: Optional notebook title - if provided, a matching H1 heading will be stripped

    Returns:
        List of StoredBlock (MarkdownBlock, VisualizationRefBlock, SessionReplayBlock)
    """
    cleaned_content = _strip_title_heading(content, title)
    return _parse_notebook_content(
        cleaned_content,
        create_insight_block=lambda artifact_id: VisualizationRefBlock(artifact_id=artifact_id),
    )


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
    cleaned_content = content
    if strip_incomplete_tags:
        cleaned_content = _strip_incomplete_insight_tags(content)

    return _parse_notebook_content(
        cleaned_content,
        create_insight_block=lambda artifact_id: LoadingBlock(artifact_id=artifact_id),
    )


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
