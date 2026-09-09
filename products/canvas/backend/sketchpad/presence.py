from typing import Any

from posthog.collab_stream import PRESENCE_EVENT_TYPE, publish_presence_entry
from posthog.dataclasses import frozen

PRESENCE_STREAM_KEY_PATTERN = "sketchpad:{{{team_id}:{sketchpad_id}}}:presence"
PRESENCE_MAX_SELECTED_IDS = 50
PRESENCE_MAX_CARETS = 4


@frozen
class SketchpadPresencePing:
    client_id: str
    actor: dict[str, Any]
    cursor: dict[str, float] | None
    viewport: dict[str, float] | None
    selected_ids: list[str]
    carets: list[dict[str, str | None]]


def publish_presence(team_id: int, sketchpad_id: str, ping: SketchpadPresencePing) -> None:
    stream_key = PRESENCE_STREAM_KEY_PATTERN.format(team_id=team_id, sketchpad_id=sketchpad_id)
    publish_presence_entry(
        stream_key,
        {
            "type": PRESENCE_EVENT_TYPE,
            "client_id": ping.client_id,
            **ping.actor,
            "cursor": ping.cursor,
            "viewport": ping.viewport,
            "selected_ids": ping.selected_ids,
            "carets": ping.carets,
        },
        log_name="sketchpad",
    )
