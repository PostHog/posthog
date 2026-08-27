"""Remove injected-context blocks from recorded message text.

An LLM judge reading a session cannot tell an injected block from something the person typed,
so it grades the assistant against its own instructions: it credits the assistant for research
the block already contained, and fails it for wording the block told it to use. Replacing each
block with a short note keeps the turn in place while removing the text that misleads.

This is a read-path transform. The stored event keeps the block, because the trace view is
where someone works out why an agent answered the way it did.
"""

import re

from .constants import INJECTED_CONTEXT_NOTE, INJECTED_CONTEXT_TAGS

_TAG_ALTERNATION = "|".join(re.escape(tag) for tag in INJECTED_CONTEXT_TAGS)

# The trailing `.*\Z` alternative catches a block whose closing tag is gone, which happens when
# an oversized payload was cut before capture. Matching only the well-formed shape would leave
# the whole remainder of the turn in place, and leave it silently: the person reading the judge's
# verdict sees no sign that the strip did nothing.
_INJECTED_BLOCK = re.compile(
    rf"<(?P<tag>{_TAG_ALTERNATION})\b[^>]*>(?:.*?</(?P=tag)>|.*\Z)",
    re.DOTALL,
)


def strip_injected_context_blocks(text: str) -> str:
    """Replace every injected-context block in `text` with a note naming the tag.

    Matching is on the tag alone, so text that quotes one of these tags verbatim is replaced
    too. That trade is deliberate here: on a judge's read path a false positive costs a slice
    of context, where leaving a real block in place costs a wrong verdict. The desktop UI makes
    the opposite trade for `user_custom_instructions`, matching a fixed preamble, because there
    a false positive hides words the person actually typed.
    """
    if "<" not in text:
        return text
    return _INJECTED_BLOCK.sub(lambda match: INJECTED_CONTEXT_NOTE.format(tag=match.group("tag")), text)
