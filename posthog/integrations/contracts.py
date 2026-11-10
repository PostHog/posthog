"""Data shapes and errors of the integrations SDK."""

import dataclasses
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Protocol

from posthog.dataclasses import frozen
from posthog.integrations.enums import AuthType

# A value that `find`, `list` and `exists` can compare a config key with. Equality only.
ConfigValue = str | int | float | bool | None

# A row that holds the typed-in credentials of a warehouse source stores the source type under this
# config key. Only `IntegrationManager.source(kind)` and a reader from `with_source_rows()` read these rows.
SOURCE_MARKER_CONFIG_KEY = "warehouse_source_type"


class IntegrationRecord(Protocol):
    """One integration row, as the SDK returns it. Read-only.

    With the Django backend the SDK returns the Django model, but callers see only these reads. So
    mypy rejects `.save()`, `.delete()`, managers and writes to `config`. Write through the SDK, for
    example with `update` or `upsert`. Other backends return a `FrozenIntegrationRecord` with the same
    reads, so callers do not change. Add a read here only when callers need it, and never a related
    row: use `team_id` and `created_by_id`, and load the team or the user from their own models.
    """

    @property
    def id(self) -> int: ...

    # The stored string form of a reference to the row. See `references.py`. Store this, not `id`:
    # rows in the credentials service have no int id.
    @property
    def reference(self) -> str: ...

    @property
    def team_id(self) -> int: ...

    @property
    def kind(self) -> str: ...

    # The id of the connection in the external system, for example a GitHub installation id.
    @property
    def integration_id(self) -> str | None: ...

    @property
    def config(self) -> Mapping[str, Any]: ...

    @property
    def sensitive_config(self) -> Mapping[str, Any]: ...

    @property
    def errors(self) -> str: ...

    @property
    def created_at(self) -> datetime: ...

    @property
    def created_by_id(self) -> int | None: ...

    # `config["auth_type"]`, or the default auth type of the kind when the row does not store one.
    @property
    def auth_type(self) -> str: ...

    # The name the UI shows for the connection, for example the account or host.
    @property
    def display_name(self) -> str: ...

    # The decrypted `sensitive_config["access_token"]`. Raises `UndecryptedIntegrationSecretError`
    # when the stored value cannot be decrypted.
    @property
    def access_token(self) -> str | None: ...

    @property
    def refresh_token(self) -> str | None: ...

    def can_be_managed_by_creator(self, user_id: int | None) -> bool: ...


def creator_can_manage(kind: str, created_by_id: int | None, user_id: int | None) -> bool:
    """True when the user who created the row can manage it without admin access."""
    return user_id is not None and kind == "google-calendar" and created_by_id == user_id


@frozen
class FrozenIntegrationRecord:
    """An `IntegrationRecord` that holds its values. The backends that do not use the Django model return it.

    The backend computes `auth_type` and `display_name` when it builds the record, so a record never
    reads the catalogue or another row.
    """

    id: int
    reference: str
    team_id: int
    kind: str
    integration_id: str | None
    config: Mapping[str, Any]
    sensitive_config: Mapping[str, Any] = dataclasses.field(repr=False)
    errors: str
    created_at: datetime
    created_by_id: int | None
    auth_type: str
    display_name: str

    # A dict field cannot hash, and callers put rows in sets and dict keys, like model instances.
    def __hash__(self) -> int:
        return hash((type(self), self.reference))

    @property
    def access_token(self) -> str | None:
        return self.sensitive_config.get("access_token")

    @property
    def refresh_token(self) -> str | None:
        return self.sensitive_config.get("refresh_token")

    def can_be_managed_by_creator(self, user_id: int | None) -> bool:
        return creator_can_manage(self.kind, self.created_by_id, user_id)


@frozen
class KindSpec:
    """The auth types of one integration kind. A row without `config["auth_type"]` has the default."""

    label: str
    default: AuthType
    others: frozenset[AuthType] = frozenset()

    @property
    def supported(self) -> frozenset[AuthType]:
        return self.others | {self.default}


@frozen
class IntegrationPatch:
    """A change to one row. `update` and `update_by_external_id` apply it.

    `errors=None` keeps the stored errors. Pass `""` to clear them.
    """

    config_patch: Mapping[str, object] = dataclasses.field(default_factory=dict)
    config_remove: tuple[str, ...] = ()
    sensitive_config_patch: Mapping[str, object] = dataclasses.field(default_factory=dict)
    sensitive_config_remove: tuple[str, ...] = ()
    errors: str | None = None


@frozen
class IntegrationUsage:
    """One PostHog object that uses an integration row, such as a warehouse source or a workflow."""

    # The kind of object, for example "warehouse_source". The product that reports it chooses the value.
    type: str
    id: str
    name: str


class IntegrationNotFound(LookupError):
    """The row does not exist, belongs to another team, or is not in the scope of the accessor."""


class UnknownIntegrationKind(ValueError):
    """The kind is not in the catalogue, and no product registered it."""


class UnsupportedIntegrationFilter(ValueError):
    """`where` holds a key or a value that the SDK cannot compare.

    The SDK compares named config keys for equality. Anything more needs its own SDK method.
    """


class UnsupportedAuthType(ValueError):
    """The kind does not support the auth type of the write."""


class IntegrationConflict(ValueError):
    """A write hit the unique key (team, kind, external id) of a row.

    `create` raises it for any row with the same key. `upsert` raises it for a row with the same key
    that the accessor cannot write, for example a row with another auth type, or a warehouse source
    row found through a named accessor.
    """


class IntegrationInUse(Exception):
    """`delete` found PostHog objects that use the row."""

    def __init__(self, usages: list[IntegrationUsage]) -> None:
        super().__init__(f"The integration has {len(usages)} usages")
        self.usages = usages
