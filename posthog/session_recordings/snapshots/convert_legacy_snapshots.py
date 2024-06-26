import json

import structlog
from prometheus_client import Histogram

from posthog.session_recordings.models.session_recording import SessionRecording
from posthog.session_recordings.session_recording_helpers import decompress
from posthog.storage import object_storage

logger = structlog.get_logger(__name__)

RECORDING_CONVERSION_TIME_HISTOGRAM = Histogram(
    "recording_conversion_time_seconds",
    "We convert legacy recordings from LTS format to the latest format, how long does that take?",
)


def _save_converted_content_back_to_storage(converted_content: str, recording: SessionRecording) -> str:
    try:
        from ee.session_recordings.session_recording_extensions import (
            save_recording_with_new_content,
        )

        return save_recording_with_new_content(recording, converted_content)
    except ImportError:
        # not running in EE context... shouldn't get here
        logger.exception(
            "attempted_to_save_converted_content_back_to_storage_in_non_ee_context",
            recording_id=recording.id,
        )
        return ""


def convert_original_version_lts_recording(recording: SessionRecording) -> str:
    # the original version of the LTS recording was a single file
    # its contents were gzipped and then base64 encoded.
    # we can't simply stream it back to the requester

    with RECORDING_CONVERSION_TIME_HISTOGRAM.time():
        content = object_storage.read(str(recording.object_storage_path))
        if not content:
            # TODO and if there's no content is this right?
            logger.error(
                "attempted_to_convert_original_version_lts_recording_with_no_content",
                recording_id=recording.id,
                object_storage_path=recording.object_storage_path,
            )
            return ""

        converted_content = _prepare_legacy_content(content)

        original_path = recording.object_storage_path
        new_file_key = _save_converted_content_back_to_storage(converted_content, recording)

        # TODO we should delete the old recording from storage here, but might not have permissions
        object_storage.tag(str(original_path), {"converted": "true"})

        return new_file_key


def _prepare_legacy_content(content: str) -> str:
    # historically we stored the recording as a single file with a base64 encoded gzipped json string
    # using utf-16 encoding, this `decompress` method unwinds that back to a json string
    decoded_content = decompress(content)
    json_content = json.loads(decoded_content)
    return _convert_legacy_format_from_lts_storage(json_content)


def _convert_legacy_format_from_lts_storage(lts_formatted_data: dict) -> str:
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
