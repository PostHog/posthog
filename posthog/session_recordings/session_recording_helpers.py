import gzip
import json
import base64
from collections import defaultdict
from collections.abc import Callable, Generator
from datetime import UTC, datetime
from typing import Any

from dateutil.parser import parse
from prometheus_client import Counter

from posthog.exceptions_capture import capture_exception
from posthog.metrics import LABEL_RESOURCE_TYPE
from posthog.session_recordings.models.metadata import SessionRecordingEventSummary
from posthog.utils import flatten

FULL_SNAPSHOT = 2
ARBITRARY_LOOP_LIMIT = 10

# NOTE: For reference here are some helpful enum mappings from rrweb
# https://github.com/rrweb-io/rrweb/blob/master/packages/rrweb/src/types.ts

# event.type

EVENTS_RECEIVED_WITHOUT_BYTES_COUNTER = Counter(
    "recording_events_received_without_bytes",
    "We want all recording events to be received with snapshot bytes so we can simplify processing, tagged by resource type.",
    labelnames=[LABEL_RESOURCE_TYPE],
)


class RRWEB_MAP_EVENT_TYPE:
    DomContentLoaded = 0
    Load = 1
    FullSnapshot = 2
    IncrementalSnapshot = 3
    Meta = 4
    Custom = 5
    Plugin = 6


# event.data.source
class RRWEB_MAP_EVENT_DATA_SOURCE:
    Mutation = 0
    MouseMove = 1
    MouseInteraction = 2
    Scroll = 3
    ViewportResize = 4
    Input = 5
    TouchMove = 6
    MediaInteraction = 7
    StyleSheetRule = 8
    CanvasMutation = 9
    Font = 1
    Log = 1
    Drag = 1
    StyleDeclaration = 1
    Selection = 1


# event.data.type
class RRWEB_MAP_EVENT_DATA_TYPE:
    MouseUp = 0
    MouseDown = 1
    Click = 2
    ContextMenu = 3
    DblClick = 4
    Focus = 5
    Blur = 6
    TouchStart = 7
    TouchMove_Departed = 8
    TouchEnd = 9
    TouchCancel = 10


# List of properties from the event payload we care about for our uncompressed `events_summary`
# NOTE: We should keep this as minimal as possible
EVENT_SUMMARY_DATA_INCLUSIONS = [
    "type",
    "source",
    "tag",
    "plugin",
    "href",
    "width",
    "height",
    "payload.href",
    "payload.level",
]


Event = dict[str, Any]


def split_replay_events(events: list[Event]) -> tuple[list[Event], list[Event]]:
    replay, other = [], []

    for event in events:
        replay.append(event) if is_unprocessed_snapshot_event(event) else other.append(event)

    return replay, other


# TODO is this covered by enough tests post-blob ingester rollout
def preprocess_replay_events_for_blob_ingestion(
    events: list[Event], max_size_bytes=1024 * 1024, user_agent: str | None = None
) -> list[Event]:
    return _process_windowed_events(
        events, lambda x: preprocess_replay_events(x, max_size_bytes=max_size_bytes, user_agent=user_agent)
    )


def snapshot_library_fallback_from(user_agent: str | None) -> str | None:
    try:
        if user_agent is None:
            fallback = None
        else:
            fallback = "web"
            if "posthog" in user_agent.lower() and "/" in user_agent:
                # mobile SDKs send e.g. posthog-android/1.0.0
                fallback = user_agent.split("/")[0]

        return fallback
    except:
        return None


def preprocess_replay_events(
    _events: list[Event] | Generator[Event, None, None], max_size_bytes=1024 * 1024, user_agent: str | None = None
) -> Generator[Event, None, None]:
    """
    The events going to blob ingestion are uncompressed (the compression happens in the Kafka producer)
    1. Since posthog-js {version} we are grouping events on the frontend in a batch and passing their size in $snapshot_bytes
       These are easy to group as we can simply make sure the total size is not higher than our max message size in Kafka.
       If one message has this property, they all do (thanks to batching).
    2. If this property isn't set, we estimate the size (json.dumps) and if it is small enough - merge it all together in one event
    3. If not, we split out the "full snapshots" from the rest (they are typically bigger) and send them individually,
            trying one more time to group the rest, otherwise sending them individually
    """

    if isinstance(_events, Generator):
        # we check the first item in the events below so need to be dealing with a list
        events = list(_events)
    else:
        events = _events

    if len(events) == 0:
        return

    size_with_headroom = max_size_bytes * 0.90  # Leave 10% headroom

    distinct_id = events[0]["properties"]["distinct_id"]
    session_id = events[0]["properties"]["$session_id"]
    window_id = events[0]["properties"].get("$window_id")
    snapshot_source = events[0]["properties"].get("$snapshot_source", "web")
    # truncate to 1000 chars just in case
    lib_property = events[0]["properties"].get("$lib", snapshot_library_fallback_from(user_agent))
    if (lib_property is not None) and (len(lib_property) > 1000):
        lib_property = lib_property[:997] + "..."

    def new_event(items: list[dict] | None = None) -> Event:
        return {
            **events[0],
            "event": "$snapshot_items",  # New event name to avoid confusion with the old $snapshot event
            "properties": {
                "distinct_id": distinct_id,
                "$session_id": session_id,
                "$window_id": window_id or session_id,
                # We instantiate here instead of in the arg to avoid mutable default args
                "$snapshot_items": items or [],
                "$snapshot_source": snapshot_source,
                "$lib": lib_property,
            },
        }

    def split_list(xs: list) -> list[list]:
        mid = len(xs) // 2
        return [xs[:mid], xs[mid:]]

    # 1. Group by $snapshot_bytes if any of the events have it
    if events[0]["properties"].get("$snapshot_bytes"):
        current_event: dict | None = None
        current_event_size = 0

        for event in events:
            additional_bytes = event["properties"]["$snapshot_bytes"]
            additional_data = flatten([event["properties"]["$snapshot_data"]], max_depth=1)

            if not current_event or current_event_size + additional_bytes > size_with_headroom:
                # If adding the new data would put us over the max size, yield the current event and start a new one
                if current_event:
                    yield current_event
                current_event = new_event()
                current_event_size = 0

            # Add the existing data to the base event
            current_event["properties"]["$snapshot_items"].extend(additional_data)
            current_event_size += additional_bytes

        if current_event:
            yield current_event
    else:
        EVENTS_RECEIVED_WITHOUT_BYTES_COUNTER.labels(resource_type="recordings").inc()

        snapshot_data_list = list(flatten([event["properties"]["$snapshot_data"] for event in events], max_depth=1))

        # 2. Otherwise, try and group all the events if they are small enough
        if byte_size_dict(snapshot_data_list) < size_with_headroom:
            event = new_event(snapshot_data_list)
            yield event
        else:
            # 3. If not, split out the full snapshots from the rest
            full_snapshots = []
            other_snapshots = []

            for snapshot_data in snapshot_data_list:
                if snapshot_data["type"] == RRWEB_MAP_EVENT_TYPE.FullSnapshot:
                    full_snapshots.append(snapshot_data)
                else:
                    other_snapshots.append(snapshot_data)

            # Send the full snapshots individually
            for snapshot_data in full_snapshots:
                event = new_event([snapshot_data])
                yield event

            # Try and group the rest
            if byte_size_dict(other_snapshots) < size_with_headroom:
                event = new_event(other_snapshots)
                yield event
            else:
                # If not, keep splitting the list until all parts fit within headroom
                # we want to avoid sending them all individually if we can - there could be tens of thousands
                # in data from these older clients that batched poorly
                parts = [other_snapshots]
                loop_count = 0
                while parts and loop_count < ARBITRARY_LOOP_LIMIT:
                    loop_count += 1
                    new_parts = []
                    for part in parts:
                        if byte_size_dict(part) < size_with_headroom:
                            event = new_event(part)
                            yield event
                        elif len(part) > 1:  # Only split if the part has more than one item
                            new_parts.extend(split_list(part))
                        else:
                            # If part has only one item and still doesn't fit, yield it as is
                            event = new_event(part)
                            yield event
                    parts = new_parts

                # finally, in the case where the list was split ten times
                # and there are still items probably over the headroom
                # we have to try to emit each remaining part individually
                # there's a strong chance these fail, but it should be
                # the vast minority of cases, if it even does happen
                if parts:
                    for part in parts:
                        event = new_event(part)
                        yield event


def _process_windowed_events(
    events: list[Event], fn: Callable[[list[Any]], Generator[Event, None, None]]
) -> list[Event]:
    """
    Helper method to simplify grouping events by window_id and session_id, processing them with the given function,
    and then returning the flattened list
    """
    result: list[Event] = []
    snapshots_by_session_and_window_id = defaultdict(list)

    for event in events:
        session_id = event["properties"]["$session_id"]
        window_id = event["properties"].get("$window_id")
        snapshots_by_session_and_window_id[(session_id, window_id)].append(event)

    for _, snapshots in snapshots_by_session_and_window_id.items():
        result.extend(fn(snapshots))

    return result


def is_unprocessed_snapshot_event(event: dict) -> bool:
    try:
        is_snapshot = event["event"] == "$snapshot"
    except KeyError:
        raise ValueError('All events must have the event name field "event"!')
    except TypeError:
        raise ValueError(f"All events must be dictionaries not '{type(event).__name__}'!")
    try:
        return is_snapshot and "compression" not in event["properties"]["$snapshot_data"]
    except KeyError:
        capture_exception()
        raise ValueError('$snapshot events must contain property "$snapshot_data"!')


# this is kept around as we upgrade older recordings in long term storage on demand.
# TODO: remove this once all recordings are upgraded
def decompress(base64data: str) -> str:
    compressed_bytes = base64.b64decode(base64data)
    return gzip.decompress(compressed_bytes).decode("utf-16", "surrogatepass")


def is_active_event(event: SessionRecordingEventSummary) -> bool:
    """
    Determines which rr-web events are "active" - meaning user generated
    """
    active_rr_web_sources = [
        1,  # MouseMove,
        2,  # MouseInteraction,
        3,  # Scroll,
        4,  # ViewportResize,
        5,  # Input,
        6,  # TouchMove,
        7,  # MediaInteraction,
        12,  # Drag,
    ]
    return event["type"] == 3 and event["data"].get("source") in active_rr_web_sources


def parse_snapshot_timestamp(timestamp: int):
    return datetime.fromtimestamp(timestamp / 1000, UTC)


def convert_to_timestamp(source: str) -> int:
    return int(parse(source).timestamp() * 1000)


def byte_size_dict(x: dict | list) -> int:
    json_str = json.dumps(x)
    # this is what kafka is going to do before sending the data
    # and deciding whether it will reject on size
    json_bytes = json_str.encode("utf-8")
    return len(json_bytes)
