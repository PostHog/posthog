import re
from collections.abc import Callable
from typing import TypeVar

from posthog.schema import LoadingBlock, MarkdownBlock

from ee.hogai.artifacts.types import StoredBlock, VisualizationRefBlock

# Insight short IDs are alphanumeric, but the model sometimes emits ids that carry a colon or
# hyphen, so accept those too rather than drop the tag back to literal text.
_INSIGHT_SHORT_ID = r"[\w:-]+"

# Every insight-reference dialect Max emits, converted to a VisualizationRefBlock. The attribute
# form is matched first because it is the only one whose id lives in an `id=`/`shortId=` attribute.
# Keep this grammar in sync with the frontend parser in
# frontend/src/lib/components/MarkdownNotebook/notebookAI.ts.
INSIGHT_TAG_PATTERN = (
    rf"<insight\b[^>]*?\b(?:id|shortId)\s*=\s*[\"'](?P<attr_id>{_INSIGHT_SHORT_ID})[\"'][^>]*?>(?:\s*</insight\s*>)?"
    rf"|<insight\s*=\s*[\"']?(?P<eq_id>{_INSIGHT_SHORT_ID})[\"']?\s*/?>(?:\s*</insight\s*>)?"
    rf"|<insight\s*>\s*(?P<el_id>{_INSIGHT_SHORT_ID})\s*</insight\s*>"
)

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
    for match in re.finditer(INSIGHT_TAG_PATTERN, content, flags=re.IGNORECASE):
        # Add markdown block for text before the tag
        if match.start() > last_end:
            text = content[last_end : match.start()].strip()
            if text:
                blocks.append(MarkdownBlock(content=text))

        # Add insight block using the factory. Exactly one dialect group matches per tag.
        artifact_id = (match.group("attr_id") or match.group("eq_id") or match.group("el_id")).strip()
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
    Strip an incomplete insight tag at the end of content (for streaming support).

    Covers every dialect INSIGHT_TAG_PATTERN accepts (element, attribute, equals; any letter
    case), so a half-streamed tag never flashes as raw markdown before the next chunk completes
    it. IGNORECASE mirrors the parser, which also matches tags case-insensitively.
    """
    cleaned = content
    # Partial opening tag name: <i, <in, ... <insight (any case).
    cleaned = re.sub(r"<i(?:n(?:s(?:i(?:g(?:h(?:t)?)?)?)?)?)?$", "", cleaned, flags=re.IGNORECASE)
    # Element form still streaming its id: <insight>partial, with no closing tag yet.
    cleaned = re.sub(r"<insight>[^<]*$", "", cleaned, flags=re.IGNORECASE)
    # Attribute or equals form that has not reached its closing '>' yet: <insight id="ab, <insight=ab.
    cleaned = re.sub(r"<insight(?:\s+[^<>]*|\s*=[^<>]*)$", "", cleaned, flags=re.IGNORECASE)
    # Partial closing tag: </i, </in, ... </insight.
    cleaned = re.sub(r"</i(?:n(?:s(?:i(?:g(?:h(?:t)?)?)?)?)?)?$", "", cleaned, flags=re.IGNORECASE)
    # Element form with content but only a partial closing tag: <insight>abc</insig.
    cleaned = re.sub(r"<insight>[^<]*</i(?:n(?:s(?:i(?:g(?:h(?:t)?)?)?)?)?)?$", "", cleaned, flags=re.IGNORECASE)
    return cleaned
