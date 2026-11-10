"""The storage seam of the integrations SDK. See "Storage backends" in `posthog/integrations/README.md`.

The accessors read and write rows only through `current_backend()`. `DjangoBackend` is the default.
Tests swap in a `FakeBackend` with `posthog.integrations.testing.fake_integrations_backend`.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from posthog.integrations.backend.django_backend import DjangoBackend
from posthog.integrations.backend.protocol import (
    KindScope,
    NewIntegration,
    RowFilter,
    RowScope,
    SourceRows,
    StorageBackend,
    TokenRefresh,
)

_backend: StorageBackend = DjangoBackend()


def current_backend() -> StorageBackend:
    return _backend


@contextmanager
def use_backend(backend: StorageBackend) -> Iterator[StorageBackend]:
    """Send every SDK operation to `backend` inside the block, in every thread. For tests."""
    global _backend
    previous = _backend
    _backend = backend
    try:
        yield backend
    finally:
        _backend = previous


__all__ = [
    "DjangoBackend",
    "KindScope",
    "NewIntegration",
    "RowFilter",
    "RowScope",
    "SourceRows",
    "StorageBackend",
    "TokenRefresh",
    "current_backend",
    "use_backend",
]
