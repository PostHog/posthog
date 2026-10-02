import json
import hashlib
from typing import TYPE_CHECKING, Literal

from posthog.dataclasses import frozen

if TYPE_CHECKING:
    from posthog.llm.system_one import JsonValue

SourceKind = Literal["skill", "metric", "certification", "relationship", "business_knowledge"]
CONFIG_VERSION = "context-selection-v5"
MAX_PROMPT_CHARS = 20_000
MAX_HISTORY_CHARS = 12_000
MAX_CONTEXT_CHARS = 8_000
MAX_ITEMS = 5
GATE_THRESHOLD = 0.3
RELEVANCE_THRESHOLD = 0.7
SOURCE_LIMITS: dict[SourceKind, int] = {
    "skill": 18,
    "metric": 8,
    "certification": 3,
    "relationship": 3,
    "business_knowledge": 8,
}


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


@frozen
class Candidate:
    id: str
    kind: SourceKind
    title: str
    text: str
    revision: str
    status: str
    reference: str
    document_id: str = ""
    tables: tuple[str, ...] = ()

    def as_json(self) -> dict[str, JsonValue]:
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "text": self.text,
            "revision": self.revision,
            "status": self.status,
            "reference": self.reference,
            "document_id": self.document_id,
            "tables": list(self.tables),
        }


@frozen
class SelectionInput:
    message_id: str
    prompt: str
    history: str = ""
    prompt_char_count: int = 0
    history_source: str = "unknown"
    runtime_version: str = "unknown"


@frozen
class PreparedContext:
    selection_id: str = ""
    context: str = ""
    mode: str = "disabled"
    reason: str = "disabled"
