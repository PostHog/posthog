from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

# Ambient caller tag sent as the x-caller-tag gRPC header so the personhog router can attribute
# traffic to the originating call site (it is "unknown" otherwise). Follows the fleet convention
# of "{area}/{operation}", e.g. "conversations/widget-allowed-ids".
_caller_tag: ContextVar[str] = ContextVar("personhog_caller_tag", default="unknown")


def current_caller_tag() -> str:
    return _caller_tag.get()


@contextmanager
def personhog_caller_tag(tag: str) -> Iterator[None]:
    """Tag personhog calls made within this block so the router attributes them to ``tag``."""
    token = _caller_tag.set(tag)
    try:
        yield
    finally:
        _caller_tag.reset(token)
