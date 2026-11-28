from ...facade import api


class MalformedTraceIdSegmentError(ValueError):
    pass


class UnreadableSessionIdError(ValueError):
    pass


def decode_trace_id_segment(segment: str) -> str:
    try:
        return api.decode_url_segment(segment)
    except api.MalformedUrlSegmentError as error:
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
    return api.encode_url_segment(trace_id)
