import dataclasses
from datetime import datetime, timedelta
from typing import List, cast, Dict, Literal

import posthoganalytics
import requests
from django.http import HttpResponse
from rest_framework import exceptions
from rest_framework.response import Response

from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.session_recordings.realtime_snapshots import get_realtime_snapshots
from posthog.session_recordings.snapshots.convert_legacy_format import (
    convert_original_version_lts_recording,
)
from posthog.session_recordings.snapshots.serializer import SessionRecordingSnapshotsSerializer
from posthog.storage import object_storage


@dataclasses.dataclass(frozen=True)
class SnapshotLoadingContext:
    team_id: str
    source: Literal["blob", "realtime"]
    blob_key: str | None
    recording: SessionRecording
    distinct_id: str
    event_properties: Dict


def load_snapshots_for(context: SnapshotLoadingContext) -> HttpResponse | Response:
    if context.source == "blob":
        return _load_blob_snapshots(context)
    elif context.source == "realtime":
        response_data = _load_realtime_snapshots(context)
        serializer = SessionRecordingSnapshotsSerializer(response_data)
        return Response(serializer.data)
    else:
        raise exceptions.ValidationError("Invalid source. Must be one of [realtime, blob]")


def _load_realtime_snapshots(loader_context: SnapshotLoadingContext) -> Dict:
    snapshots = (
        get_realtime_snapshots(
            team_id=loader_context.team_id, session_id=cast(str, loader_context.recording.session_id)
        )
        or []
    )

    loader_context.event_properties["source"] = "realtime"
    loader_context.event_properties["snapshots_length"] = len(snapshots)
    posthoganalytics.capture(
        loader_context.distinct_id, "session recording snapshots v2 loaded", loader_context.event_properties
    )

    return {"snapshots": snapshots}


def gather_snapshot_sources(recording: SessionRecording) -> Dict:
    sources: List[dict] = []
    might_have_realtime = True
    newest_timestamp = None
    blob_keys: List[str] = []

    if recording.object_storage_path:
        blob_prefix = recording.object_storage_path
        if recording.storage_version == "2023-08-01":
            blob_keys = object_storage.list_objects(cast(str, recording.object_storage_path))
        else:
            # originally LTS stored recordings were a single file
            sources.append(
                {
                    "source": "blob",
                    "start_timestamp": recording.start_time,
                    "end_timestamp": recording.end_time,
                    "blob_key": recording.object_storage_path,
                }
            )
            might_have_realtime = False

    else:
        blob_prefix = recording.build_blob_ingestion_storage_path()
        blob_keys = object_storage.list_objects(blob_prefix)

    if blob_keys:
        for full_key in blob_keys:
            # Keys are like 1619712000-1619712060
            blob_key = full_key.replace(blob_prefix.rstrip("/") + "/", "")
            time_range = [datetime.fromtimestamp(int(x) / 1000) for x in blob_key.split("-")]

            sources.append(
                {
                    "source": "blob",
                    "start_timestamp": time_range[0],
                    "end_timestamp": time_range.pop(),
                    "blob_key": blob_key,
                }
            )

    if sources:
        sources = sorted(sources, key=lambda x: x["start_timestamp"])
        oldest_timestamp = min(sources, key=lambda k: k["start_timestamp"])["start_timestamp"]
        newest_timestamp = min(sources, key=lambda k: k["end_timestamp"])["end_timestamp"]

        if might_have_realtime:
            might_have_realtime = oldest_timestamp + timedelta(hours=24) > datetime.utcnow()

    if might_have_realtime:
        sources.append(
            {
                "source": "realtime",
                "start_timestamp": newest_timestamp,
                "end_timestamp": None,
            }
        )

    return {"sources": sources}


def _load_blob_snapshots(loader_context: SnapshotLoadingContext) -> HttpResponse:
    # This is the case when a legacy lts recording is loaded (single file)
    is_single_file_legacy_recording = loader_context.recording.object_storage_path == loader_context.blob_key
    if is_single_file_legacy_recording:
        file_key = loader_context.recording.object_storage_path
    else:
        file_key = (
            f"{loader_context.recording.object_storage_path}/{loader_context.blob_key}"
            if loader_context.recording.object_storage_path
            else f"{loader_context.recording.build_blob_ingestion_storage_path()}/{loader_context.blob_key}"
        )

    # very short-lived pre-signed URL
    url = object_storage.get_presigned_url(file_key, expiration=60)
    if not url:
        raise exceptions.NotFound("Snapshot file not found")

    loader_context.event_properties["source"] = "blob"
    loader_context.event_properties["blob_key"] = loader_context.blob_key
    posthoganalytics.capture(
        loader_context.distinct_id, "session recording snapshots v2 loaded", loader_context.event_properties
    )

    with requests.get(url=url, stream=True) as r:
        r.raise_for_status()
        if is_single_file_legacy_recording:
            # this is likely "legacy" base64 encoded gzipped data
            # so, we need to decode it before returning it
            return convert_original_version_lts_recording(r, loader_context.recording, url)
        else:
            # this is a newer format we can stream directly to the client
            response = HttpResponse(content=r.raw, content_type="application/json")
            response["Content-Disposition"] = "inline"
            return response
