from posthog.dataclasses import frozen

THREAD_CONTEXT_TAGS = ("slack_thread_context", "slack_thread_context_update")
_INITIATOR_PLACEHOLDER = "<original user message was here>"
# The Slack app sends this title when the mention carried no text; the request is then the
# message, inside the block, from the person its role line names as having tagged the app.
_EMPTY_REQUEST = "Task from Slack"
# Role lines the Slack app writes at the start of a header line. Display names cannot hold a newline,
# so a name that repeats this wording cannot start a line.
_MENTIONER_ROLES = ("Tagged the PostHog app: ", "Thread started by and tagged the PostHog app: ")


@frozen
class ThreadMessage:
    author: str
    body: str


@frozen
class SplitPrompt:
    request: str
    thread: tuple[ThreadMessage, ...] = ()


def _mentioner(header: str) -> str:
    for line in header.split("\n"):
        for role in _MENTIONER_ROLES:
            if line.startswith(role):
                return line.removeprefix(role).rsplit(" (", 1)[0]
    return ""


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
        # The Slack app strips both tags from participant text, so a tag here is one it rendered. The update
        # block's header names the original tag in prose, so only a tag that ends its line opens a block.
        opened = [(rest.find(f"<{tag}>\n"), tag) for tag in THREAD_CONTEXT_TAGS]
        found = [(start, tag) for start, tag in opened if start >= 0]
        if not found:
            break
        start, tag = min(found)
        closing = f"</{tag}>"
        end = rest.find(closing, start)
        if end < 0:
            break
        block_mentioner, messages = _thread_messages(rest[start + len(tag) + 2 : end])
        mentioner = mentioner or block_mentioner
        thread.extend(messages)
        rest = rest[:start] + rest[end + len(closing) :]
    request = rest.strip()
    mentioned = [i for i, message in enumerate(thread) if mentioner and message.author == mentioner]
    if request == _EMPTY_REQUEST and mentioned:
        # Replies posted after the mention can follow it in the block, so the last message is not
        # always the request. Without the mentioner's message, no one else's words stand in for it.
        request = thread.pop(mentioned[-1]).body
    return SplitPrompt(request=request, thread=tuple(thread))
