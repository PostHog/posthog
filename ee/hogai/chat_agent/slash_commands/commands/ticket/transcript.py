import re
from collections.abc import Sequence

from posthog.schema import AssistantMessage, HumanMessage

from ee.hogai.utils.types import AssistantMessageUnion

TICKET_COMMAND = "/ticket"

_QUOTED_SPAN = re.compile(r'["“]([^"“”]+)["”]')
_SMART_QUOTES = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'"})


def _customer_text(message: HumanMessage) -> str | None:
    """The customer's own words, with the slash command removed. None when nothing is left."""
    content = message.content.strip()
    if content == TICKET_COMMAND:
        return None
    if content.startswith(f"{TICKET_COMMAND} "):
        content = content[len(TICKET_COMMAND) :].strip()
    return content or None


def customer_turns(messages: Sequence[AssistantMessageUnion]) -> list[str]:
    """Every customer message that carries content, in order."""
    turns: list[str] = []
    for message in messages:
        if isinstance(message, HumanMessage):
            text = _customer_text(message)
            if text:
                turns.append(text)
    return turns


def render_transcript(messages: Sequence[AssistantMessageUnion]) -> str:
    """Render the conversation as a tagged document for the summarizer to read as source material."""
    rendered: list[str] = []
    for message in messages:
        if isinstance(message, HumanMessage):
            text = _customer_text(message)
            if text:
                rendered.append(f"<customer>\n{text}\n</customer>")
        elif isinstance(message, AssistantMessage) and message.content:
            rendered.append(f"<posthog_ai>\n{message.content}\n</posthog_ai>")
    return "\n".join(rendered)


def _normalize(text: str) -> str:
    collapsed = re.sub(r"\s+", " ", text.translate(_SMART_QUOTES).replace("'", '"'))
    return collapsed.strip(" .,;:!?")


def _quote_matches(span: str, normalized_turns: Sequence[str]) -> bool:
    fragments = [fragment for fragment in span.split("...") if fragment.strip()]
    if not fragments:
        return False
    return any(all(_normalize(fragment) in turn for fragment in fragments) for turn in normalized_turns)


def quoted_spans(summary: str) -> list[str]:
    """Every span the summary presents as the customer's own words."""
    return _QUOTED_SPAN.findall(summary)


def unverifiable_quotes(summary: str, turns: Sequence[str]) -> list[str]:
    """Quoted spans that no single customer message contains."""
    normalized = [_normalize(turn) for turn in turns]
    return [span for span in quoted_spans(summary) if not _quote_matches(span, normalized)]


def strip_unverifiable_quotes(summary: str, turns: Sequence[str]) -> str:
    """Drop the quotation marks around any span the customer did not actually write.

    A span is kept only when one customer message contains all of it, so a quote cannot be
    assembled from words the customer used in different messages.
    """
    normalized = [_normalize(turn) for turn in turns]

    def keep_or_unquote(match: re.Match[str]) -> str:
        return match.group(0) if _quote_matches(match.group(1), normalized) else match.group(1)

    return _QUOTED_SPAN.sub(keep_or_unquote, summary)
