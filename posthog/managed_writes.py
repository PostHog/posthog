"""Guards that refuse an API write to an object another system owns, such as an entity a stack manages in code.

A product declares its guards as `WRITE_GUARDS` in `backend/facade/write_guards.py`. Core finds them with
`load_product_modules`, and `ManagedWritePermission` in `posthog/permissions.py` runs them on every object a
`TeamAndOrgViewSetMixin` view loads for an unsafe request. A route that writes without loading its object that
way, such as a bulk action, calls `enforce_managed_writes` in `posthog/permissions.py` itself.
This module imports no DRF, so a product facade can import the types.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import cache
from typing import Any

from posthog.dataclasses import frozen
from posthog.products import load_product_modules

GUARDS_MODULE = "facade.write_guards"
GUARDS_ATTRIBUTE = "WRITE_GUARDS"


@frozen
class ObjectWrite:
    team_id: int
    # The Django label of the object's model, such as "feature_flags.FeatureFlag".
    model_label: str
    object_id: str
    # The view action, such as "partial_update", "destroy" or a custom action's name.
    action: str | None
    is_delete: bool
    # The client id of the request's OAuth application, only when that application is first party.
    first_party_client_id: str | None
    # The id of the request's OAuth access token, so a guard can tell one live run's token from the application's
    # other tokens.
    oauth_token_id: str | None
    # Reads one attribute of the object as a string, or None when it has none.
    attribute: Callable[[str], str | None]
    # Given candidate fields, the ones whose value in the request differs from the object's current value.
    changed_fields: Callable[[frozenset[str]], list[str]]


@frozen
class WriteRefusal:
    code: str
    detail: str
    # Added to the error body beside `code` and `detail`.
    extra: dict[str, Any]


@frozen
class WriteGuard:
    model_labels: frozenset[str]
    check: Callable[[ObjectWrite], WriteRefusal | None]


class WriteGuardError(Exception):
    pass


@cache
def write_guards() -> tuple[WriteGuard, ...]:
    guards: list[WriteGuard] = []
    for module in load_product_modules(GUARDS_MODULE):
        declared = getattr(module, GUARDS_ATTRIBUTE, None)
        if not isinstance(declared, tuple) or not all(isinstance(guard, WriteGuard) for guard in declared):
            raise WriteGuardError(f"{module.__name__}.{GUARDS_ATTRIBUTE} must be a tuple of WriteGuard")
        guards.extend(declared)
    return tuple(guards)


@cache
def guarded_model_labels() -> frozenset[str]:
    return frozenset(label for guard in write_guards() for label in guard.model_labels)


def refusal_for(write: ObjectWrite) -> WriteRefusal | None:
    for guard in write_guards():
        if write.model_label in guard.model_labels:
            refusal = guard.check(write)
            if refusal is not None:
                return refusal
    return None
