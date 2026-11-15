import re
import json
import uuid
import base64
import random
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import NotRequired, TypedDict

import requests

SAMPLE_TRACES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "sample_traces"

ID_KEYS = frozenset(
    {
        "$ai_trace_id",
        "$ai_parent_id",
        "$ai_span_id",
        "$ai_generation_id",
        "$ai_session_id",
        "$session_id",
        "$ai_target_event_id",
        "$ai_target_id",
        "$ai_evaluation_id",
        "$ai_response_id",
        "conversation_id",
    }
)
UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
HEX_RE = re.compile(r"[0-9a-f]+")
MEDIA_RE = re.compile(r"⟦media:([^⟧]+)⟧")
MAX_BATCH_BYTES = 5_000_000


class SampleEvent(TypedDict):
    event: str
    uuid: NotRequired[str]
    offset_ms: int
    distinct_id: str
    properties: dict[str, object]


class CaptureEvent(TypedDict):
    event: str
    uuid: str
    distinct_id: str
    timestamp: str
    properties: dict[str, object]


class SampleTraces:
    def __init__(self, root: Path = SAMPLE_TRACES_DIR) -> None:
        self.root = root

    def sets(self) -> dict[str, list[str]]:
        doc = json.loads((self.root / "sets.json").read_text())
        return {name: sorted(members) for name, members in doc.items() if not name.startswith("_")}

    def unit_ids(self, set_name: str = "core", only: list[str] | None = None) -> list[str]:
        all_ids = sorted(path.stem for path in (self.root / "units").glob("*.json"))
        if only is not None:
            # An empty entry would match every unit, so "--only foo," must not select everything.
            wanted = [entry.strip() for entry in only if entry.strip()]
            if not wanted:
                raise ValueError("--only needs at least one unit id or substring")
            return [uid for uid in all_ids if any(entry in uid for entry in wanted)]
        if set_name == "all":
            return all_ids
        sets = self.sets()
        if set_name not in sets:
            raise ValueError(f"Unknown set {set_name!r}, expected one of {sorted(sets)} or 'all'")
        return sets[set_name]

    def events(self, unit_id: str) -> list[SampleEvent]:
        return json.loads((self.root / "units" / f"{unit_id}.json").read_text())["events"]

    def inline_media(self, text: str) -> str:
        return MEDIA_RE.sub(lambda m: base64.b64encode((self.root / "media" / m.group(1)).read_bytes()).decode(), text)


def fresh_id_like(value: str, rng: random.Random) -> str:
    if UUID_RE.fullmatch(value):
        return str(uuid.UUID(int=rng.getrandbits(128), version=4))
    if HEX_RE.fullmatch(value):
        return "".join(rng.choice("0123456789abcdef") for _ in value)
    return f"{value}-{rng.getrandbits(32):08x}"


def _collect_ids(node: object, found: set[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ID_KEYS and isinstance(value, str) and value:
                found.add(value)
            _collect_ids(value, found)
    elif isinstance(node, list):
        for value in node:
            _collect_ids(value, found)


def remap_ids(events: list[SampleEvent], rng: random.Random) -> list[SampleEvent]:
    """Give every trace, span and session id a fresh value, keeping the links between events intact."""
    found: set[str] = set()
    _collect_ids([e["properties"] for e in events], found)
    text = json.dumps(events, ensure_ascii=False)
    found.update(UUID_RE.findall(text))
    for old in sorted(found, key=len, reverse=True):
        new = fresh_id_like(old, rng)
        # Only uuids are safe to replace inside free text; other ids could match ordinary words.
        text = text.replace(old, new) if UUID_RE.fullmatch(old) else text.replace(f'"{old}"', f'"{new}"')
    return json.loads(text)


def build_capture_events(
    samples: SampleTraces, unit_id: str, end_at: datetime, rng: random.Random
) -> list[CaptureEvent]:
    events = remap_ids(samples.events(unit_id), rng)
    start = end_at - timedelta(milliseconds=max(e["offset_ms"] for e in events))
    user_prefix = f"sample-{rng.getrandbits(24):06x}"
    return [
        {
            "event": e["event"],
            "uuid": e.get("uuid") or str(uuid.UUID(int=rng.getrandbits(128), version=4)),
            "distinct_id": f"{user_prefix}-{e['distinct_id']}",
            "timestamp": (start + timedelta(milliseconds=e["offset_ms"])).isoformat(),
            "properties": json.loads(samples.inline_media(json.dumps(e["properties"], ensure_ascii=False))),
        }
        for e in events
    ]


def _chunks(events: list[CaptureEvent]) -> Iterator[list[CaptureEvent]]:
    chunk: list[CaptureEvent] = []
    size = 0
    for event in events:
        event_size = len(json.dumps(event))
        if chunk and size + event_size > MAX_BATCH_BYTES:
            yield chunk
            chunk, size = [], 0
        chunk.append(event)
        size += event_size
    if chunk:
        yield chunk


def seed(
    token: str,
    host: str,
    unit_ids: list[str],
    days: float,
    samples: SampleTraces | None = None,
    now: datetime | None = None,
) -> dict[str, int]:
    """Post each unit through capture, spreading units over the last `days` days. Returns events sent per unit."""
    samples = samples or SampleTraces()
    now = now or datetime.now(UTC)
    rng = random.Random()
    sent: dict[str, int] = {}
    for index, unit_id in enumerate(unit_ids):
        end_at = now - timedelta(days=days * (len(unit_ids) - 1 - index) / max(1, len(unit_ids)), minutes=5)
        events = build_capture_events(samples, unit_id, end_at, rng)
        for chunk in _chunks(events):
            response = requests.post(f"{host}/batch/", json={"api_key": token, "batch": chunk}, timeout=60)
            response.raise_for_status()
        sent[unit_id] = len(events)
    return sent
