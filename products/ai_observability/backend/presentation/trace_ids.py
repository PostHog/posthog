import re
import base64
import binascii

# Trace ids are free-form, and the server decodes "%2F" before routing, so a raw id with a "/" cannot travel
# as one path segment. The client always sends the unpadded base64url of the id's UTF-8 bytes instead.
# Keep this in sync with encodeTraceIdSegment in the frontend.
_BASE64URL = re.compile(r"[A-Za-z0-9_-]+")


class MalformedTraceIdSegmentError(ValueError):
    pass


def decode_trace_id_segment(segment: str) -> str:
    if not _BASE64URL.fullmatch(segment):
        raise MalformedTraceIdSegmentError(segment)
    try:
        return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError) as error:
        raise MalformedTraceIdSegmentError(segment) from error
