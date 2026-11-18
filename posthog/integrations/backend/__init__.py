"""The storage seam of the integrations SDK. See "Storage backends" in `posthog/integrations/README.md`.

The accessors read and write rows only through `current_backend()`. `DjangoBackend` is the default.
Tests swap in a `FakeBackend` with `posthog.integrations.testing.fake_integrations_backend`.
"""

from collections.abc import Iterator
from contextlib import contextmanager

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

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
from posthog.integrations.backend.service_backend import ServiceBackend

_backend: StorageBackend | None = None


def configured_backend() -> StorageBackend:
    """The backend that `INTEGRATIONS_STORAGE_BACKEND` names."""
    name = settings.INTEGRATIONS_STORAGE_BACKEND
    if name == "django":
        return DjangoBackend()
    if name == "service":
        return ServiceBackend()
    raise ImproperlyConfigured(f"INTEGRATIONS_STORAGE_BACKEND must be 'django' or 'service', not {name!r}")


def current_backend() -> StorageBackend:
    global _backend
    # Read the setting on first use, not at import, so importing the SDK does not need Django settings.
    if _backend is None:
        _backend = configured_backend()
    return _backend


def database_read_aliases() -> list[str]:
    """The Django database aliases that SDK reads use now. Empty when the backend reads no Django database.

    A caller that caps its reads with a statement timeout per alias passes these with its own aliases.
    """
    if not isinstance(_backend, DjangoBackend):
        return []
    # Deferred: the database helpers import Django models.
    from posthog.ingress.dispatch.database import read_aliases  # noqa: PLC0415
    from posthog.models.integration.model import Integration  # noqa: PLC0415

    return read_aliases([Integration])


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
    "ServiceBackend",
    "SourceRows",
    "StorageBackend",
    "TokenRefresh",
    "configured_backend",
    "current_backend",
    "database_read_aliases",
    "use_backend",
]
