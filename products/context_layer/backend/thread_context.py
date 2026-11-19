from posthog.dataclasses import frozen

THREAD_CONTEXT_TAGS = ("slack_thread_context", "slack_thread_context_update")
_INITIATOR_PLACEHOLDER = "<original user message was here>"
# The Slack app sends this title when the mention carried no text; the request is then the
# message, inside the block, from the person its role line names as having tagged the app.
_EMPTY_REQUEST = "Task from Slack"
_MENTIONER_ROLE = "tagged the posthog app: "


@frozen
class ThreadMessage:
    author: str
    body: str


@frozen
class SplitPrompt:
    request: str
    thread: tuple[ThreadMessage, ...] = ()


def _mentioner(header: str) -> str:
    start = header.lower().find(_MENTIONER_ROLE)
    if start < 0:
        return ""
    return header[start + len(_MENTIONER_ROLE) :].split("\n")[0].rsplit(" (", 1)[0]


def _thread_messages(block: str) -> tuple[str, list[ThreadMessage]]:
    # The block opens with a header that ends at the first blank line. Each message after it is
    # an unindented `author:` line followed by its body, indented two spaces.
    header, separator, entries = block.partition("\n\n")
    if not separator:
        return "", []
    messages: list[tuple[str, list[str]]] = []
    for line in entries.split("\n"):
        if line and not line[0].isspace():
            messages.append((line.removesuffix(":"), []))
        elif messages:
            messages[-1][1].append(line.removeprefix("  "))
    parsed = [ThreadMessage(author=author, body="\n".join(lines).strip()) for author, lines in messages]
    return _mentioner(header), [message for message in parsed if message.body != _INITIATOR_PLACEHOLDER]


def split_thread_context(text: str) -> SplitPrompt:
    """Separate the Slack thread blocks in a prompt from the request around them."""
    thread: list[ThreadMessage] = []
    mentioner = ""
    rest = text
    while True:
        # A real opening tag ends its line. A tag named in header prose or forged in a display name does
        # not, because display names cannot hold a newline.
        opened = [(rest.find(f"<{tag}>\n"), tag) for tag in THREAD_CONTEXT_TAGS]
        found = [(start, tag) for start, tag in opened if start >= 0]
        if not found:
            break
        start, tag = min(found)
        closing = f"</{tag}>"
        # Message bodies arrive with these tags stripped, but display names do not, so a forged closing
        # tag can only come before the real one, which is the last before the next block opens.
        later = [i for i in (rest.find(f"<{other}>\n", start + 1) for other in THREAD_CONTEXT_TAGS) if i >= 0]
        end = rest.rfind(closing, start, min(later, default=len(rest)))
        if end < 0:
            break
        block_mentioner, messages = _thread_messages(rest[start + len(tag) + 2 : end])
        mentioner = mentioner or block_mentioner
        thread.extend(messages)
        rest = rest[:start] + rest[end + len(closing) :]
    request = rest.strip()
    if request == _EMPTY_REQUEST and thread:
        # Replies posted after the mention can follow it in the block, so the last message is not
        # always the request.
        mentioned = [i for i, message in enumerate(thread) if message.author == mentioner]
        request = thread.pop(mentioned[-1] if mentioned else -1).body
    return SplitPrompt(request=request, thread=tuple(thread))
