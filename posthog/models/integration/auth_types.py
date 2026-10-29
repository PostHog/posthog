"""Auth types of `Integration` rows, and the catalogue of the auth types that each kind supports.

A kind names the provider (`github`, `stripe`, `postgresql`). An auth type names how the row
authenticates with that provider: `oauth` (a connection the provider manages), `token` (one static
secret) or `credentials` (several typed-in fields). A kind can have several auth types. Each kind
has one default auth type: the meaning the kind had before auth types existed. A row stores its auth
type in `config["auth_type"]` only when it is not the default. A row without that key has the
default auth type of its kind, so rows written before auth types existed need no migration.

Code outside the integrations SDK (`posthog/integrations/`) does not query the model. The SDK
states the auth types of each query with the internal `IntegrationQuerySet._with_auth`.

This module must not import `model.py`: `model.py` imports it to build the queryset filters. It
imports only the light SDK modules (catalogue, contracts, enums), which do not import the model.
"""

from collections.abc import Iterable, Mapping
from enum import Enum
from typing import Any, Self

from django.db.models import Q

from posthog.dataclasses import frozen
from posthog.integrations.catalogue import KINDS
from posthog.integrations.contracts import SOURCE_MARKER_CONFIG_KEY, KindSpec
from posthog.integrations.enums import IntegrationAuthType

AUTH_TYPE_CONFIG_KEY = "auth_type"


# The auth types and the kind catalogue belong to the integrations SDK. The model reads them here for
# the storage rule and the implicit default filter of the model manager.
KindAuthTypes = KindSpec


class AuthTypeSelector(Enum):
    # Every auth type. For code that handles each row the same way, such as the integrations list.
    ANY = "any"
    # The default auth type of each row's kind. For code that handles several kinds by their usual meaning.
    DEFAULT = "default"


ANY = AuthTypeSelector.ANY
DEFAULT = AuthTypeSelector.DEFAULT

# Kinds that are not in the catalogue get this entry until they register their own with
# `register_kind_auth_types`.
UNKNOWN_KIND_AUTH_TYPES = KindSpec(label="Unknown", default=IntegrationAuthType.CREDENTIALS)

_KIND_AUTH_TYPES: dict[str, KindSpec] = dict(KINDS)


def register_kind_auth_types(kind: str, auth_types: KindSpec) -> None:
    """Add a kind to the catalogue, before the first query of the kind runs. `register_source_kinds` calls it."""
    existing = _KIND_AUTH_TYPES.get(kind)
    # Adding supported auth types is safe. Changing the default is not: rows store only a non-default.
    widens = (
        existing is not None and existing.default == auth_types.default and existing.supported <= auth_types.supported
    )
    if existing is not None and existing != auth_types and not widens:
        raise ValueError(f"Integration kind {kind!r} already has auth types {existing!r}")
    _KIND_AUTH_TYPES[kind] = auth_types


def kind_auth_types(kind: str) -> KindSpec:
    return _KIND_AUTH_TYPES.get(kind, UNKNOWN_KIND_AUTH_TYPES)


def catalogued_kinds() -> Mapping[str, KindSpec]:
    return dict(_KIND_AUTH_TYPES)


def default_auth_type(kind: str) -> IntegrationAuthType:
    return kind_auth_types(kind).default


def stored_auth_type(config: Any) -> str | None:
    if not isinstance(config, dict):
        return None
    return config.get(AUTH_TYPE_CONFIG_KEY)


def effective_auth_type(kind: str, config: Any) -> str:
    stored = stored_auth_type(config)
    return stored if stored is not None else default_auth_type(kind).value


def _unset_q() -> Q:
    # `isnull=True` on a JSON key matches a missing key only. A JSON null counts as unset too,
    # the same as `config.get("auth_type")` in Python.
    return Q(config__auth_type__isnull=True) | Q(config__auth_type=None)


def _kinds_with_default_q(auth_type: IntegrationAuthType) -> Q | None:
    kinds = [kind for kind, entry in _KIND_AUTH_TYPES.items() if entry.default == auth_type]
    clauses: list[Q] = []
    if kinds:
        clauses.append(Q(kind__in=kinds))
    if UNKNOWN_KIND_AUTH_TYPES.default == auth_type:
        clauses.append(~Q(kind__in=list(_KIND_AUTH_TYPES)))
    return _any_of(clauses)


def _any_of(clauses: Iterable[Q]) -> Q | None:
    result: Q | None = None
    for clause in clauses:
        result = clause if result is None else result | clause
    return result


def rows_with_auth_type_q(auth_type: IntegrationAuthType) -> Q:
    explicit = Q(config__auth_type=auth_type.value)
    kinds = _kinds_with_default_q(auth_type)
    return explicit if kinds is None else explicit | (_unset_q() & kinds)


def rows_with_default_auth_type_q() -> Q:
    # Correct because `normalized_config` never lets a row store the default auth type of its kind.
    return _unset_q()


def rows_without_source_marker_q() -> Q:
    return ~Q(config__has_key=SOURCE_MARKER_CONFIG_KEY)


def normalized_config(kind: Any, config: Any) -> Any:
    """Drop a stored auth type that is null or the default of the kind.

    So a row has `config["auth_type"]` only when its auth type is not the default, and the filter for
    default rows stays one short clause. `Integration.save` and `bulk_create` call it.
    """
    if not isinstance(config, dict) or AUTH_TYPE_CONFIG_KEY not in config or not isinstance(kind, str):
        return config
    stored = config[AUTH_TYPE_CONFIG_KEY]
    if stored is not None and stored != default_auth_type(kind):
        return config
    return {key: value for key, value in config.items() if key != AUTH_TYPE_CONFIG_KEY}


@frozen
class AuthRequirement:
    """The auth types that a caller can handle.

    It is the input of `_with_auth`. Later it can also carry the scopes that a caller needs, so that
    one check compares them with the scopes that a row grants.
    """

    any: bool = False
    kind_default: bool = False
    auth_types: frozenset[IntegrationAuthType] = frozenset()

    @classmethod
    def of(cls, *selectors: "IntegrationAuthType | AuthTypeSelector | str") -> Self:
        if not selectors:
            raise ValueError("_with_auth() needs at least one auth type, DEFAULT or ANY")
        if ANY in selectors:
            if len(selectors) > 1:
                raise ValueError("ANY already includes every auth type, so pass it alone")
            return cls(any=True)
        auth_types: set[IntegrationAuthType] = set()
        for selector in selectors:
            if selector is DEFAULT:
                continue
            if isinstance(selector, AuthTypeSelector) or selector not in IntegrationAuthType.values:
                raise ValueError(f"Unknown integration auth type: {selector!r}")
            auth_types.add(IntegrationAuthType(selector))
        return cls(kind_default=DEFAULT in selectors, auth_types=frozenset(auth_types))

    @classmethod
    def kind_default_only(cls) -> Self:
        return cls(kind_default=True)

    def q(self) -> Q:
        if self.any:
            return Q()
        clauses = [rows_with_auth_type_q(auth_type) for auth_type in sorted(self.auth_types)]
        if self.kind_default:
            clauses.append(rows_with_default_auth_type_q())
        result = _any_of(clauses)
        assert result is not None
        return result

    def accepts(self, kind: str | None, auth_type: str) -> bool:
        if self.any or auth_type in self.auth_types:
            return True
        return self.kind_default and kind is not None and auth_type == default_auth_type(kind)

    @property
    def single_auth_type(self) -> IntegrationAuthType | None:
        if self.any or self.kind_default or len(self.auth_types) != 1:
            return None
        return next(iter(self.auth_types))


def config_for_write(kind: Any, config: Any, requirement: AuthRequirement) -> Any:
    """Return the config to write for a new or updated row under `requirement`.

    A requirement with one auth type writes it into the config when it is not the kind's default.
    A requirement that does not cover the row's auth type raises, so a write never makes a row that
    the same query cannot read back. `kind` is None when the caller does not pass it.
    """
    if config is None:
        config = {}
    if not isinstance(config, dict) or not (kind is None or isinstance(kind, str)):
        return config

    stored = stored_auth_type(config)
    if stored is not None:
        if kind is not None and stored not in kind_auth_types(kind).supported:
            raise ValueError(f"Integration kind {kind!r} does not support auth type {stored!r}")
        if not requirement.accepts(kind, stored):
            raise ValueError(f"Auth type {stored!r} is not in the _with_auth() of this query")
        return config

    target = requirement.single_auth_type
    if target is not None:
        if kind is None:
            if any(entry.default == target for entry in _KIND_AUTH_TYPES.values()):
                raise ValueError(f"Pass the kind, so the write can tell if {target.value!r} is its default")
            return {**config, AUTH_TYPE_CONFIG_KEY: target.value}
        if target not in kind_auth_types(kind).supported:
            raise ValueError(f"Integration kind {kind!r} does not support auth type {target.value!r}")
        if target == default_auth_type(kind):
            return config
        return {**config, AUTH_TYPE_CONFIG_KEY: target.value}

    if kind is not None and not requirement.accepts(kind, default_auth_type(kind).value):
        raise ValueError("A write through _with_auth() needs exactly one auth type, or one that is the kind's default")
    return config
