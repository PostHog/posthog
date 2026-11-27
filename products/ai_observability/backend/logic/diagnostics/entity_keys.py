from products.ai_observability.backend.logic.traces.url_segments import (
    MalformedUrlSegmentError,
    decode_url_segment,
    encode_url_segment,
)


class MalformedEntityKeyError(ValueError):
    pass


def encode_entity_key(value: str) -> str:
    return encode_url_segment(value)


def decode_entity_key(key: str) -> str:
    try:
        value = decode_url_segment(key)
    except MalformedUrlSegmentError as error:
        raise MalformedEntityKeyError(key) from error
    # The decoder ignores unused trailing bits, so a second key would otherwise name the same value.
    if encode_url_segment(value) != key:
        raise MalformedEntityKeyError(key)
    return value
