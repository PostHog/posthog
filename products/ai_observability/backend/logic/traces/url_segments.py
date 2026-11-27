import re
import base64
import binascii

# Trace ids, session ids, error messages and tool names are free text, and the server decodes "%2F" before routing, so
# a raw value with a "/" cannot travel as one path segment. The client sends the unpadded base64url of the value's UTF-8
# bytes instead. Keep this in sync with encodeTraceIdSegment in the frontend.
_BASE64URL = re.compile(r"[A-Za-z0-9_-]+")


class MalformedUrlSegmentError(ValueError):
    pass


def encode_url_segment(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("ascii").rstrip("=")


def decode_url_segment(segment: str) -> str:
    if not _BASE64URL.fullmatch(segment):
        raise MalformedUrlSegmentError(segment)
    try:
        return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError) as error:
        raise MalformedUrlSegmentError(segment) from error
