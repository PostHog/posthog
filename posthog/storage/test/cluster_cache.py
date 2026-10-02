from collections.abc import Iterator
from contextlib import ExitStack, contextmanager

from unittest.mock import patch

from django.core.cache.backends.base import BaseCache


@contextmanager
def reject_multi_key_commands(client: BaseCache) -> Iterator[None]:
    """Make `client` raise on any multi-key call, as a cluster does when the keys span slots."""

    def guard(name: str):
        real = getattr(client, name)

        def call(keys, *args, **kwargs):
            if len(keys) > 1:
                raise RuntimeError(f"CROSSSLOT Keys in request don't hash to the same slot ({name})")
            return real(keys, *args, **kwargs)

        return call

    with ExitStack() as stack:
        for name in ("delete_many", "get_many", "set_many"):
            stack.enter_context(patch.object(client, name, side_effect=guard(name)))
        yield
