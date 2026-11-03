"""A shared cache of the parts of team and project API output that are the same for every caller.

The key holds a team version and the org serializer version. A write to a Team, or to any model with a one-to-one
link to Team, bumps the team version. The org serializer cache bumps the org version on organization, project,
membership and access writes. A reader then builds a new value, and old entries expire on their own TTL.
A write that skips Django signals, such as a queryset `.update()`, can show its old value until the TTL ends.
"""

from typing import Any

from django.apps import apps
from django.core.cache import cache
from django.db import transaction
from django.db.models import Model
from django.db.models.signals import post_delete, post_save

import structlog

from posthog.caching.cache_version import bump_cache_version, read_cache_version
from posthog.caching.organization_serializer_cache import _org_serializer_cache_version
from posthog.git import get_git_commit_short
from posthog.models.team import Team
from posthog.utils import get_safe_cache

logger = structlog.get_logger(__name__)

TEAM_REPRESENTATION_CACHE_TTL_SECONDS = 10 * 60
_TEAM_REPRESENTATION_VERSION_TTL_SECONDS = 7 * 24 * 60 * 60


def _team_version_key(team_id: int) -> str:
    return f"team_representation_version:{team_id}"


def team_representation_cache_key(name: str, team_id: int, organization_id: str) -> str:
    team_version = read_cache_version(_team_version_key(team_id), _TEAM_REPRESENTATION_VERSION_TTL_SECONDS)
    org_version = _org_serializer_cache_version(organization_id)
    # A deploy can change the output shape, so a new build never reads entries an older build wrote.
    build = get_git_commit_short() or "unknown"
    return f"team_representation:{build}:{name}:{team_id}:t{team_version}:o{org_version}"


def get_team_representation(key: str) -> dict[str, Any] | None:
    cached = get_safe_cache(key)
    return cached if isinstance(cached, dict) else None


def set_team_representation(key: str, representation: dict[str, Any]) -> None:
    def write() -> None:
        try:
            cache.set(key, representation, timeout=TEAM_REPRESENTATION_CACHE_TTL_SECONDS)
        except Exception:
            logger.warning("team_representation_cache_write_failed", exc_info=True)

    # Inside a transaction the value can hold rows that roll back, so it is written only after the commit.
    transaction.on_commit(write)


def _bump_team_version(team_id: int) -> None:
    bump_cache_version(_team_version_key(team_id), _TEAM_REPRESENTATION_VERSION_TTL_SECONDS)


def _connect_invalidation(model: type[Model], team_id_attname: str) -> None:
    def receiver_fn(sender: type[Model], instance: Any, **kwargs: Any) -> None:
        team_id = getattr(instance, team_id_attname, None)
        if team_id is None:
            return
        _bump_team_version(team_id)
        # A read between this write and its commit can cache the old rows under the new version.
        transaction.on_commit(lambda: _bump_team_version(team_id))

    post_save.connect(receiver_fn, sender=model, weak=False)
    post_delete.connect(receiver_fn, sender=model, weak=False)


def connect_team_representation_invalidation() -> None:
    """Connects Team and every model with a one-to-one link to Team, so a new team extension needs no change here."""
    _connect_invalidation(Team, "id")
    for model in apps.get_models():
        for field in model._meta.concrete_fields:
            if field.one_to_one and field.related_model is Team:
                _connect_invalidation(model, field.attname)
