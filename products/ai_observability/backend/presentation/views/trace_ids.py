import re
import base64
import binascii

from ...facade import api

# Trace ids are free-form, and the server decodes "%2F" before routing, so a raw id with a "/" cannot travel
# as one path segment. The client always sends the unpadded base64url of the id's UTF-8 bytes instead.
# Session ids travel the same way. Keep this in sync with encodeTraceIdSegment in the frontend.
_BASE64URL = re.compile(r"[A-Za-z0-9_-]+")


class MalformedTraceIdSegmentError(ValueError):
    pass


class UnreadableSessionIdError(ValueError):
    pass


def decode_trace_id_segment(segment: str) -> str:
    if not _BASE64URL.fullmatch(segment):
        raise MalformedTraceIdSegmentError(segment)
    try:
        return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError) as error:
        raise MalformedTraceIdSegmentError(segment) from error


def decode_session_id_segment(segment: str) -> str:
    """Raises `UnreadableSessionIdError` for a segment that does not decode, and for a session id longer than any the
    sessions list hands out."""
    try:
        session_id = decode_trace_id_segment(segment)
    except MalformedTraceIdSegmentError as error:
        raise UnreadableSessionIdError(segment) from error
    if len(session_id) > api.SESSION_ID_MAX_LENGTH:
        raise UnreadableSessionIdError(segment)
    return session_id


def encode_trace_id_segment(trace_id: str) -> str:
    return base64.urlsafe_b64encode(trace_id.encode("utf-8")).decode("ascii").rstrip("=")
