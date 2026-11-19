from posthog.dataclasses import frozen

THREAD_CONTEXT_TAGS = ("slack_thread_context", "slack_thread_context_update")
_INITIATOR_PLACEHOLDER = "<original user message was here>"
# The Slack app sends this title when the mention carried no text; the request is then the
# last thread message, from the person who tagged the app.
_EMPTY_REQUEST = "Task from Slack"


@frozen
class ThreadMessage:
    author: str
    body: str


@frozen
class SplitPrompt:
    request: str
    thread: tuple[ThreadMessage, ...] = ()


def _thread_messages(block: str) -> list[ThreadMessage]:
    # The block opens with a header that ends at the first blank line. Each message after it is
    # an unindented `author:` line followed by its body, indented two spaces.
    _, separator, entries = block.partition("\n\n")
    if not separator:
        return []
    messages: list[tuple[str, list[str]]] = []
    for line in entries.split("\n"):
        if line and not line[0].isspace():
            messages.append((line.removesuffix(":"), []))
        elif messages:
            messages[-1][1].append(line.removeprefix("  "))
    parsed = [ThreadMessage(author=author, body="\n".join(lines).strip()) for author, lines in messages]
    return [message for message in parsed if message.body != _INITIATOR_PLACEHOLDER]


def split_thread_context(text: str) -> SplitPrompt:
    """Separate the Slack thread blocks in a prompt from the request around them."""
    thread: list[ThreadMessage] = []
    rest = text
    while True:
        opened = [(rest.find(f"<{tag}>"), tag) for tag in THREAD_CONTEXT_TAGS]
        found = [(start, tag) for start, tag in opened if start >= 0]
        if not found:
            break
        start, tag = min(found)
        closing = f"</{tag}>"
        end = rest.find(closing, start)
        if end < 0:
            break
        thread.extend(_thread_messages(rest[start + len(tag) + 2 : end]))
        rest = rest[:start] + rest[end + len(closing) :]
    request = rest.strip()
    if request == _EMPTY_REQUEST and thread:
        request = thread.pop().body
    return SplitPrompt(request=request, thread=tuple(thread))
