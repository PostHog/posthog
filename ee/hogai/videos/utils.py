import math
from io import BytesIO

import structlog
from pymediainfo import MediaInfo

logger = structlog.get_logger(__name__)


def get_video_duration_s(video_bytes: bytes) -> int:
    """Extract duration in seconds from video bytes to understand when the export UI finished rendering"""
    media_info = MediaInfo.parse(BytesIO(video_bytes))
    for track in media_info.tracks:
        if track.track_type == "General":
            if track.duration is None:
                raise ValueError("General track duration is None")
            # Convert ms to seconds, ceil to avoid grey "not-rendered" frames at the start
            return int(math.ceil(track.duration / 1000.0))
    raise ValueError("No General track found in video to extract duration from")
