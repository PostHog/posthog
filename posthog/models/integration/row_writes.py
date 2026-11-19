"""How the per-kind adapters write their own row: through the integrations SDK, never with `save()`.

An adapter holds the row that the SDK returns after a write. Callers outside this package can
still hold the row that they gave to the adapter, and read its tokens after a refresh. So
`keep_caller_row_current` copies the stored values into that row while it is a model instance.
It goes away when the SDK returns frozen records.
"""

from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING

from posthog.integrations.contracts import SOURCE_MARKER_CONFIG_KEY, IntegrationPatch, IntegrationRecord
from posthog.integrations.enums import AuthType

from . import model
from .auth_types import AUTH_TYPE_CONFIG_KEY, default_auth_type

if TYPE_CHECKING:
    from posthog.integrations.accessors import AuthAccessor, OAuthAccessor
    from posthog.integrations.backend.protocol import SourceRows

# The SDK writes these config keys itself, so a patch cannot set or remove them.
_SDK_CONFIG_KEYS = frozenset({AUTH_TYPE_CONFIG_KEY, SOURCE_MARKER_CONFIG_KEY})


def _source_rows(record: IntegrationRecord) -> "SourceRows":
    from posthog.integrations.backend.protocol import SourceRows  # noqa: PLC0415 — the SDK imports the adapters

    return SourceRows.ONLY if SOURCE_MARKER_CONFIG_KEY in record.config else SourceRows.EXCLUDE


def row_accessor(record: IntegrationRecord) -> "AuthAccessor":
    """The SDK accessor whose scope holds exactly the kind, the auth type and the source flag of this row."""
    from posthog.integrations.accessors import AuthAccessor  # noqa: PLC0415 — the SDK imports the adapters

    return AuthAccessor(kind=record.kind, auth_type=AuthType(record.auth_type), source_rows=_source_rows(record))


def creator_accessor(kind: str) -> "AuthAccessor":
    """The SDK accessor that a creator of `kind` writes through: the default auth type, no warehouse source rows.

    Use `upsert` for a reconnect (it clears `errors`, and `created_by_id=None` keeps the creator), or
    `create` for a row that must be new.
    """
    from posthog.integrations.accessors import AuthAccessor  # noqa: PLC0415 — the SDK imports the adapters

    return AuthAccessor(kind=kind, auth_type=default_auth_type(kind))


def oauth_row_accessor(record: IntegrationRecord) -> "OAuthAccessor":
    """The SDK accessor that refreshes the OAuth tokens of this row."""
    from posthog.integrations.accessors import OAuthAccessor  # noqa: PLC0415 — the SDK imports the adapters

    return OAuthAccessor(kind=record.kind, source_rows=_source_rows(record))


def keep_caller_row_current(original: IntegrationRecord, fresh: IntegrationRecord) -> None:
    """Copy the stored values of `fresh` into `original`, the row that the caller gave to the adapter."""
    if original is fresh or not isinstance(original, model.Integration):
        return
    original.config = dict(fresh.config)
    original.sensitive_config = dict(fresh.sensitive_config)
    original.errors = fresh.errors


def update_row(record: IntegrationRecord, patch: IntegrationPatch) -> IntegrationRecord:
    """Store `patch` on the row of `record` under the row lock of the SDK. Returns the stored row."""
    fresh = row_accessor(record).update(
        record.team_id,
        record.id,
        config_patch=patch.config_patch,
        config_remove=patch.config_remove,
        sensitive_config_patch=patch.sensitive_config_patch,
        sensitive_config_remove=patch.sensitive_config_remove,
        errors=patch.errors,
    )
    keep_caller_row_current(record, fresh)
    return fresh


def reread_row(record: IntegrationRecord) -> IntegrationRecord:
    """Read the row of `record` again, after a write that did not return it."""
    fresh = row_accessor(record).get(record.team_id, record.id)
    keep_caller_row_current(record, fresh)
    return fresh


def merged_patch(*patches: IntegrationPatch) -> IntegrationPatch:
    """One patch with the changes of all `patches`. When two patches change one key, the later one wins."""
    config: dict[str, object] = {}
    config_remove: dict[str, None] = {}
    sensitive_config: dict[str, object] = {}
    sensitive_config_remove: dict[str, None] = {}
    errors: str | None = None
    for patch in patches:
        _merge(config, config_remove, patch.config_patch, patch.config_remove)
        _merge(sensitive_config, sensitive_config_remove, patch.sensitive_config_patch, patch.sensitive_config_remove)
        if patch.errors is not None:
            errors = patch.errors
    return IntegrationPatch(
        config_patch=config,
        config_remove=tuple(config_remove),
        sensitive_config_patch=sensitive_config,
        sensitive_config_remove=tuple(sensitive_config_remove),
        errors=errors,
    )


def _merge(
    values: dict[str, object], removed: dict[str, None], patch: Mapping[str, object], remove: Iterable[str]
) -> None:
    for key, value in patch.items():
        values[key] = value
        removed.pop(key, None)
    for key in remove:
        values.pop(key, None)
        removed[key] = None


def replaced_config_patch(current: Mapping[str, object], new: Mapping[str, object]) -> IntegrationPatch:
    """The patch that replaces the whole config with `new`. It keeps the keys that the SDK writes."""
    removed = tuple(key for key in current if key not in new and key not in _SDK_CONFIG_KEYS)
    return IntegrationPatch(config_patch=dict(new), config_remove=removed)


def replaced_sensitive_config_patch(current: Mapping[str, object], new: Mapping[str, object]) -> IntegrationPatch:
    """The patch that replaces the whole sensitive config with `new`."""
    return IntegrationPatch(
        sensitive_config_patch=dict(new),
        sensitive_config_remove=tuple(key for key in current if key not in new),
    )
