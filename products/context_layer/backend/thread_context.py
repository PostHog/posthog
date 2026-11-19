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
    # The first line of the message that opened the thread, such as an alert's title.
    subject: str = ""


def _mentioner(header: str) -> str:
    for line in header.split("\n"):
        for role in _MENTIONER_ROLES:
            if line.startswith(role):
                return line.removeprefix(role).rsplit(" (", 1)[0]
    return ""


def _first_line(text: str) -> str:
    return next((line.strip() for line in text.splitlines() if line.strip()), "")


@frozen
class _Block:
    mentioner: str
    messages: tuple[ThreadMessage, ...]
    requester_opened: bool


def _parse_block(block: str) -> _Block:
    # The block opens with a header that ends at the first blank line. Each message after it is
    # an unindented `author:` line followed by its body, indented two spaces.
    header, separator, entries = block.partition("\n\n")
    if not separator:
        return _Block(mentioner="", messages=(), requester_opened=False)
    messages: list[tuple[str, list[str]]] = []
    for line in entries.split("\n"):
        if line and not line[0].isspace():
            messages.append((line.removesuffix(":"), []))
        elif messages:
            messages[-1][1].append(line.removeprefix("  "))
    parsed = [ThreadMessage(author=author, body="\n".join(lines).strip()) for author, lines in messages]
    return _Block(
        mentioner=_mentioner(header),
        messages=tuple(message for message in parsed if message.body != _INITIATOR_PLACEHOLDER),
        requester_opened=bool(parsed) and parsed[0].body == _INITIATOR_PLACEHOLDER,
    )


def _drop_truncated_block(text: str) -> str:
    # The agent keeps only the end of a long prompt or history, which can cut a block's opening tag but
    # keep its closing tag. Participant text holds no tags, so a closing tag before any opening one ends
    # a truncated block, and everything up to it is thread text.
    openings = [i for i in (text.find(f"<{tag}>\n") for tag in THREAD_CONTEXT_TAGS) if i >= 0]
    head = text[: min(openings, default=len(text))]
    closings = [(head.rfind(f"</{tag}>"), tag) for tag in THREAD_CONTEXT_TAGS]
    end, tag = max(closings)
    return text[end + len(tag) + 3 :] if end >= 0 else text


def split_thread_context(text: str) -> SplitPrompt:
    """Separate the Slack thread blocks in a prompt, or in a history of prompts, from the requests around them."""
    thread: list[ThreadMessage] = []
    subject = ""
    rest = _drop_truncated_block(text)
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
        block = _parse_block(rest[start + len(tag) + 2 : end])
        messages = list(block.messages)
        # Only the original block starts at the thread's root. When the requester opened the thread,
        # the root is their request, not a subject to add.
        if tag == THREAD_CONTEXT_TAGS[0] and messages and not block.requester_opened and not subject:
            subject = _first_line(messages[0].body)
        after = rest[end + len(closing) :]
        lead = len(after) - len(after.lstrip("\n"))
        title_end = lead + len(_EMPTY_REQUEST)
        own = [i for i, message in enumerate(messages) if block.mentioner and message.author == block.mentioner]
        if after[lead:title_end] == _EMPTY_REQUEST and after[title_end : title_end + 1] in ("", "\n") and own:
            # A textless mention's request is the mentioner's own message in this block. Replies can follow
            # it, so it is their last message, and no one else's words stand in for it.
            after = after[:lead] + messages.pop(own[-1]).body + after[title_end:]
        thread.extend(messages)
        rest = rest[:start] + after
    return SplitPrompt(request=rest.strip(), thread=tuple(thread), subject=subject)
