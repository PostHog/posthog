from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from .legacy_authorization import LegacyAuthorization

legacy_evaluators: ContextVar[list[LegacyAuthorization] | None] = ContextVar("authz_legacy_evaluators", default=None)
project_organizations: ContextVar[dict[int, UUID] | None] = ContextVar("authz_project_organizations", default=None)
# Whether each (organization, user) pair is a guest membership.
guest_memberships: ContextVar[dict[tuple[UUID, int], bool] | None] = ContextVar("authz_guest_memberships", default=None)


@contextmanager
def authorization_session() -> Iterator[None]:
    token = legacy_evaluators.set([])
    projects_token = project_organizations.set({})
    guests_token = guest_memberships.set({})
    try:
        yield
    finally:
        guest_memberships.reset(guests_token)
        project_organizations.reset(projects_token)
        legacy_evaluators.reset(token)


def invalidate() -> None:
    evaluators = legacy_evaluators.get()
    if evaluators is not None:
        evaluators.clear()
    projects = project_organizations.get()
    if projects is not None:
        projects.clear()
    guests = guest_memberships.get()
    if guests is not None:
        guests.clear()
