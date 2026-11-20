"""The hooks that run when the SDK deletes or writes an integration row.

Foreign keys to `Integration` and model signals on it stop working when the rows move to the credentials
service. So the SDK calls these hooks itself, and each hook does the work of one foreign key or one
signal receiver. A product defines its hooks in `products/<product>/backend/integration_hooks.py`:

    def before_integration_delete(row: IntegrationRecord) -> None: ...
    def after_integration_saved(row: IntegrationRecord, *, created: bool, config_changed: bool) -> None: ...

A module can define one of the two functions or both. The SDK finds these modules on the first call, so
no core module has to import a product. Code outside a product calls `register_delete_hook` or
`register_saved_hook` when its module loads.

Delete hooks run in one transaction of the Django database, together with the delete of the row. A hook
that raises rolls back the work of the other hooks and keeps the row. A delete hook must be idempotent,
because the foreign keys still do the same work until they are removed. Work outside the database goes
in `transaction.on_commit`.

Saved hooks run after the write, each in its own savepoint. A saved hook that raises is logged, its
database work rolls back, and the write stays, because the row is already stored.
"""

import threading
import contextvars
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from typing import Protocol

from django.db import transaction

import structlog

from posthog.exceptions_capture import capture_exception
from posthog.integrations.contracts import IntegrationRecord
from posthog.products import load_product_modules


class DeleteHook(Protocol):
    def __call__(self, row: IntegrationRecord, /) -> None: ...


class SavedHook(Protocol):
    def __call__(self, row: IntegrationRecord, /, *, created: bool, config_changed: bool) -> None: ...


PRODUCT_MODULE = "integration_hooks"
DELETE_FUNCTION = "before_integration_delete"
SAVED_FUNCTION = "after_integration_saved"

logger = structlog.get_logger(__name__)

# Reentrant: a hook module can call a `register_*` function while `_product_hooks` imports it.
_lock = threading.RLock()
_registered_delete: list[DeleteHook] = []
_registered_saved: list[SavedHook] = []
_product_delete: list[DeleteHook] | None = None
_product_saved: list[SavedHook] | None = None

_sdk_runs_hooks: contextvars.ContextVar[bool] = contextvars.ContextVar("integrations_sdk_runs_hooks", default=False)


def register_delete_hook(hook: DeleteHook) -> None:
    with _lock:
        if hook not in _registered_delete:
            _registered_delete.append(hook)


def register_saved_hook(hook: SavedHook) -> None:
    with _lock:
        if hook not in _registered_saved:
            _registered_saved.append(hook)


def _load_product_hooks() -> None:
    global _product_delete, _product_saved
    with _lock:
        if _product_delete is not None:
            return
        modules = list(load_product_modules(PRODUCT_MODULE))
        _product_saved = [getattr(m, SAVED_FUNCTION) for m in modules if hasattr(m, SAVED_FUNCTION)]
        _product_delete = [getattr(m, DELETE_FUNCTION) for m in modules if hasattr(m, DELETE_FUNCTION)]


def delete_hooks() -> list[DeleteHook]:
    _load_product_hooks()
    with _lock:
        return [*(_product_delete or []), *_registered_delete]


def saved_hooks() -> list[SavedHook]:
    _load_product_hooks()
    with _lock:
        return [*(_product_saved or []), *_registered_saved]


def sdk_runs_hooks() -> bool:
    """True while the SDK writes or deletes a row and runs the hooks itself.

    A model signal receiver that has a hook returns early when this is True, so its work happens once.
    The receivers stay for the writers that do not use the SDK yet.
    """
    return _sdk_runs_hooks.get()


@contextmanager
def sdk_write() -> Iterator[None]:
    """Mark the block as an SDK write, so the model signal receivers leave the work to the hooks."""
    token = _sdk_runs_hooks.set(True)
    try:
        yield
    finally:
        _sdk_runs_hooks.reset(token)


@contextmanager
def sdk_delete() -> Iterator[None]:
    """One transaction of the Django database for the delete hooks and the delete of the rows.

    With a backend outside the Django database, the backend deletes the rows before this transaction
    commits. If that delete fails, the hooks roll back. If the commit fails after the delete, references
    to the deleted rows stay, and readers already handle a reference to a missing row.
    """
    with transaction.atomic(), sdk_write():
        yield


def run_delete_hooks(rows: Iterable[IntegrationRecord]) -> None:
    """Run every delete hook for each row. Call it inside `sdk_delete`, before the rows are deleted."""
    hooks = delete_hooks()
    for row in rows:
        for hook in hooks:
            hook(row)


def run_saved_hooks(row: IntegrationRecord, *, created: bool, config_changed: bool) -> None:
    for hook in saved_hooks():
        try:
            # A savepoint, so a database error in one hook does not break the caller's transaction.
            with transaction.atomic():
                hook(row, created=created, config_changed=config_changed)
        except Exception as error:
            logger.exception(
                "integrations_sdk_saved_hook_failed", kind=row.kind, hook=getattr(hook, "__qualname__", "")
            )
            capture_exception(error, {"team_id": row.team_id, "integration_kind": row.kind})
