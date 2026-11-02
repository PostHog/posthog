"""The authorization session: the current user, and the lookups every check in one scope shares."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import field
from typing import TYPE_CHECKING, Any

from django.db import connection, transaction

from posthog.dataclasses import frozen

if TYPE_CHECKING:
    from posthog.models import User

    from products.access_control.backend.facade.user_access_control import UserAccessControl

PrincipalKey = tuple[str, int]


@frozen(frozen=False)
class Session:
    """Cached rules and lookups for one request or one `authorization_session()` block.

    `principal` reads the user at check time, because DRF authenticates after the middleware.
    `uncommitted` means a rule write waits for its commit, so nothing is cached until then.
    """

    principal: Callable[[], Any] | None = None
    users: dict[int, User | None] = field(default_factory=dict)
    access: dict[PrincipalKey, UserAccessControl] = field(default_factory=dict)
    uncommitted: bool = False

    def clear(self) -> None:
        self.users.clear()
        self.access.clear()

    def committed(self) -> None:
        self.clear()
        self.uncommitted = False

    def can_cache(self) -> bool:
        # A rollback never runs `committed`, so caching resumes once no transaction is open.
        if self.uncommitted and not connection.in_atomic_block:
            self.committed()
        return not self.uncommitted


_current: ContextVar[Session | None] = ContextVar("authorization_session", default=None)


def current() -> Session | None:
    return _current.get()


@contextmanager
def scope(principal: Callable[[], Any] | None = None) -> Iterator[Session]:
    """Open a session until the block exits. A block without a principal reuses a session that is already open."""
    active = _current.get()
    if active is not None and principal is None:
        yield active
        return
    opened = Session(principal=principal)
    token = _current.set(opened)
    try:
        yield opened
    finally:
        _current.reset(token)


def invalidate(**_: Any) -> None:
    """Clear the cached rules after a rule change, so later checks in this request see it."""
    session = _current.get()
    if session is None:
        return
    session.clear()
    # A rollback sends no signal, so cache nothing until commit.
    if connection.in_atomic_block:
        session.uncommitted = True
        transaction.on_commit(session.committed)
