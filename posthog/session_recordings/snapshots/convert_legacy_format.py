import base64
import gzip
import json
from io import BytesIO
from typing import Dict

from prometheus_client import Histogram
from requests import Response
from django.http import HttpResponse
from rest_framework import exceptions
from sentry_sdk import capture_exception

from posthog.session_recordings.models.session_recording import SessionRecording

import structlog

logger = structlog.get_logger(__name__)

RECORDING_CONVERSION_TIME_HISTOGRAM = Histogram(
    "recording_conversion_time_seconds",
    "We convert legacy recordings from LTS format to the latest format, how long does that take?",
)


def _save_converted_content_back_to_storage(converted_content: str, recording: SessionRecording) -> None:
    try:
        from ee.session_recordings.session_recording_extensions import save_recording_with_new_content

        save_recording_with_new_content(recording, converted_content)
    except ImportError:
        # not running in EE context... shouldn't get here
        logger.error("attempted_to_save_converted_content_back_to_storage_in_non_ee_context", recording_id=recording.id)
        return


def convert_original_version_lts_recording(r: Response, recording: SessionRecording, url: str) -> HttpResponse:
    # the original version of the LTS recording was a single file
    # its contents were gzipped and then base64 encoded.
    # we can't simply stream it back to the requester

    with RECORDING_CONVERSION_TIME_HISTOGRAM.time():
        decoded_content = _base_64_decode_the_contents(r)
        uncompressed_content = _unzip_the_contents(decoded_content)
        json_content = _json_convert_the_contents(uncompressed_content)
        converted_content = _convert_legacy_format_from_lts_storage(json_content)

        _save_converted_content_back_to_storage(converted_content, recording)

        return HttpResponse(content=(converted_content.encode("utf-8")), content_type="application/json")


def _json_convert_the_contents(uncompressed_content: bytes) -> Dict:
    try:
        return json.loads(uncompressed_content)
    except json.JSONDecodeError:
        raise exceptions.ValidationError("The content is not valid JSON.")


def _unzip_the_contents(decoded_content: bytes) -> bytes:
    buffer = BytesIO(decoded_content)
    with gzip.GzipFile(fileobj=buffer, mode="rb") as f:
        uncompressed_content = f.read()
    return uncompressed_content


def _base_64_decode_the_contents(r: Response) -> bytes:
    try:
        decoded_content = base64.b64decode(r.content)
    except Exception:
        capture_exception()
        raise exceptions.ValidationError("Snapshot file is not valid base64")
    return decoded_content


def _convert_legacy_format_from_lts_storage(lts_formatted_data: Dict) -> str:
    """
    The latest version is JSONL formatted data.
    Each line is json containing a window_id and a data array.
    This is equivalent to the LTS format snapshot_data_by_window_id property dumped as a single line.
    """
    if "snapshot_data_by_window_id" not in lts_formatted_data:
        raise ValueError("Invalid LTS format: missing snapshot_data_by_window_id")

    if "version" not in lts_formatted_data or lts_formatted_data["version"] != "2022-12-22":
        raise ValueError(f"Invalid LTS format: version is {lts_formatted_data.get('version', 'missing')}")

    snapshot_data_by_window_id = lts_formatted_data["snapshot_data_by_window_id"]
    converted = ""
    for window_id, data in snapshot_data_by_window_id.items():
        converted += json.dumps({"window_id": window_id, "data": data}, separators=(",", ":")) + "\n"

    return converted.rstrip("\n")
