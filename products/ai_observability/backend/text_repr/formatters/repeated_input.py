import json
import hashlib
from typing import Any

# Kept in sync with TRANSPORT_METADATA_KEYS in products/ai_observability/frontend/messageSignature.ts. Callers
# change these fields between calls without changing the message, for example Anthropic incremental caching
# moves `cache_control` to the newest message on every call.
_TRANSPORT_METADATA_KEYS = frozenset({"cache_control", "signature", "caller"})


def _without_transport_metadata(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_transport_metadata(item) for key, item in value.items() if key not in _TRANSPORT_METADATA_KEYS
        }
    if isinstance(value, list):
        return [_without_transport_metadata(item) for item in value]
    return value


def _digest(message: Any) -> bytes:
    text = json.dumps(_without_transport_metadata(message), sort_keys=True, default=str)
    return hashlib.blake2b(text.encode(), digest_size=16).digest()


class RepeatedInputHistory:
    """The input messages of the generations rendered so far.

    Agent loops resend the whole conversation on every call, and sub-agents interleave their calls with the
    orchestrator's, so a generation's input is matched against every earlier input, not only the last one.
    The inputs are kept as a trie of message digests, so a lookup costs one digest per message.
    """

    def __init__(self) -> None:
        self._nodes: dict[tuple[int, bytes], int] = {}

    def add(self, messages: list[Any]) -> int:
        """Record a generation's input and return how many of its leading messages an earlier input starts with."""
        node = 0
        repeated = 0
        for message in messages:
            key = (node, _digest(message))
            if key in self._nodes:
                repeated += 1
            else:
                self._nodes[key] = len(self._nodes) + 1
            node = self._nodes[key]
        return repeated
