"""Kinds that hold the typed-in credentials of warehouse sources.

There are about a thousand of these kinds, so they get no generated accessor. The warehouse product
registers them at startup, and callers reach their rows through `IntegrationManager.source(kind)`.
A row of a source kind carries the source type in `config["warehouse_source_type"]`.
"""

import threading
from collections.abc import Mapping

from posthog.integrations.catalogue import KINDS
from posthog.integrations.contracts import SOURCE_MARKER_CONFIG_KEY, KindSpec
from posthog.integrations.enums import AuthType
from posthog.models.integration.auth_types import register_kind_auth_types

__all__ = ["SOURCE_MARKER_CONFIG_KEY", "is_source_kind", "register_source_kinds"]

_lock = threading.Lock()
_source_kinds: set[str] = set()


def register_source_kinds(kinds: Mapping[str, AuthType]) -> None:
    """Register warehouse source kinds with the default auth type of each.

    A kind that is also in the catalogue, such as `stripe` or `postgresql`, keeps its catalogue default.
    The auth type given here only joins the auth types the kind supports, so its source rows can be written.
    """
    with _lock:
        for kind, auth_type in kinds.items():
            catalogued = KINDS.get(kind)
            if catalogued is None:
                register_kind_auth_types(kind, KindSpec(label=kind, default=AuthType(auth_type)))
            elif AuthType(auth_type) not in catalogued.supported:
                register_kind_auth_types(
                    kind,
                    KindSpec(
                        label=catalogued.label,
                        default=catalogued.default,
                        others=catalogued.others | {AuthType(auth_type)},
                    ),
                )
            _source_kinds.add(kind)


def is_source_kind(kind: str) -> bool:
    return kind in _source_kinds
