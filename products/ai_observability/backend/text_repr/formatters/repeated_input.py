import hashlib
from typing import Any, Literal

from posthog.dataclasses import frozen

# Kept in sync with TRANSPORT_METADATA_KEYS in products/ai_observability/frontend/messageSignature.ts. Callers
# change these fields between calls without changing the message, for example Anthropic incremental caching
# moves `cache_control` to the newest message on every call. They are ignored only on a message, a dict with a
# role, and on its content blocks, dicts with a type, so a tool payload with one of these names still counts.
_TRANSPORT_METADATA_KEYS = frozenset({"cache_control", "signature", "caller"})
_BLOCK_LIST_KEYS = frozenset({"content", "parts"})
_STRING_CHUNK_CHARS = 1 << 16
# Each indexed message costs about 300 bytes, and a trace's message count has no limit before the render
# budget applies, so the history stops indexing new messages here. It still matches the ones it holds.
MAX_INDEXED_MESSAGES = 20_000

_Level = Literal["message", "blocks", "block", "payload"]


def _digest(message: Any) -> bytes:
    """A digest of the message without its transport metadata.

    It walks the message with a stack instead of serializing it, so a large message is never copied whole and a
    deeply nested one cannot exceed the recursion limit.
    """
    hasher = hashlib.blake2b(digest_size=16)
    stack: list[bytes | tuple[Any, _Level]] = [(message, "message")]
    while stack:
        item = stack.pop()
        if isinstance(item, bytes):
            hasher.update(item)
            continue
        value, level = item
        if isinstance(value, dict):
            transport = (level == "message" and "role" in value) or (level == "block" and "type" in value)
            keys = sorted((key for key in value if not (transport and key in _TRANSPORT_METADATA_KEYS)), key=str)
            hasher.update(b"{%d" % len(keys))
            stack.append(b"}")
            for key in reversed(keys):
                child: _Level = "blocks" if level == "message" and key in _BLOCK_LIST_KEYS else "payload"
                stack.append((value[key], child))
                stack.append((str(key), "payload"))
        elif isinstance(value, list):
            hasher.update(b"[%d" % len(value))
            stack.append(b"]")
            item_level: _Level = "block" if level == "blocks" else "payload"
            stack.extend((element, item_level) for element in reversed(value))
        elif isinstance(value, str):
            hasher.update(b"s%d:" % len(value))
            for start in range(0, len(value), _STRING_CHUNK_CHARS):
                hasher.update(value[start : start + _STRING_CHUNK_CHARS].encode("utf-8", "surrogatepass"))
        else:
            hasher.update(f"{type(value).__name__}:{value!r};".encode("utf-8", "surrogatepass"))
    return hasher.digest()


@frozen
class RepeatedInput:
    # Leading input messages that an earlier generation's input starts with.
    messages: int
    # The latest earlier generation with those messages, numbered from 1 in render order.
    generation: int


class RepeatedInputHistory:
    """The input messages of the generations rendered so far.

    Agent loops resend the whole conversation on every call, and sub-agents interleave their calls with the
    orchestrator's, so a generation's input is matched against every earlier input, not only the last one.
    The inputs are kept as a trie of message digests, so a lookup costs one digest per message.
    """

    def __init__(self) -> None:
        self.generations = 0
        self._nodes: dict[tuple[int, bytes], int] = {}
        self._latest_generation: dict[int, int] = {}

    def add(self, messages: list[Any]) -> RepeatedInput | None:
        """Record the next generation's input, and return the leading messages an earlier input starts with."""
        self.generations += 1
        node = 0
        repeated: RepeatedInput | None = None
        for message in messages:
            key = (node, _digest(message))
            if key in self._nodes:
                node = self._nodes[key]
                repeated = RepeatedInput(
                    messages=(repeated.messages if repeated else 0) + 1, generation=self._latest_generation[node]
                )
            else:
                if len(self._nodes) >= MAX_INDEXED_MESSAGES:
                    break
                node = self._nodes[key] = len(self._nodes) + 1
            self._latest_generation[node] = self.generations
        return repeated
