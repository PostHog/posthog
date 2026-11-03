"""
Signal handlers that keep the team metadata cache in sync with Team state.

Wired from PostHogConfig.ready() via connect_signal_handlers() so the receivers
register in every Django process that can mutate a team (web, asgi, workers).
Do not declare them in posthog.tasks.team_metadata: a web process imports that module
only when its Celery app finalizes on the first task it sends, so a save in a process
that has not sent a task yet would leave the flags service reading stale team metadata
until the hourly verification fixes it.
"""

from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_save, pre_delete

import structlog

from posthog.models.organization import Organization
from posthog.models.project import Project
from posthog.models.team import Team
from posthog.storage.hypercache_manager import HYPERCACHE_SIGNAL_UPDATE_COUNTER
from posthog.storage.team_metadata_cache import clear_team_metadata_cache

from products.feature_flags.backend.models.team_feature_flag_policy_config import TeamFeatureFlagPolicyConfig

logger = structlog.get_logger(__name__)


def _record_enqueue_failure() -> None:
    HYPERCACHE_SIGNAL_UPDATE_COUNTER.labels(
        namespace="team_metadata", cache_name="team_metadata", operation="enqueue", result="failure"
    ).inc()


def _enqueue_team_metadata_update_on_commit(team_id: int) -> None:
    def enqueue_task() -> None:
        # posthog.tasks.__init__ eagerly imports every task module (celery autoimport);
        # this signal module is wired at django.setup(), so import the task lazily.
        from posthog.tasks.team_metadata import update_team_metadata_cache_task  # noqa: PLC0415

        try:
            update_team_metadata_cache_task.delay(team_id)
        except Exception as e:
            _record_enqueue_failure()
            logger.exception(
                "Failed to enqueue cache update task",
                team_id=team_id,
                error=str(e),
            )

    # Use transaction.on_commit to ensure the database changes are committed
    # before we update the cache
    transaction.on_commit(enqueue_task)


def _enqueue_related_team_metadata_fanout(*, organization_id: int | None = None, project_id: int | None = None) -> None:
    # Imported lazily for the same reason as in _enqueue_team_metadata_update_on_commit.
    from posthog.tasks.team_metadata import update_related_teams_metadata_cache_task  # noqa: PLC0415

    try:
        update_related_teams_metadata_cache_task.delay(organization_id=organization_id, project_id=project_id)
    except Exception as e:
        _record_enqueue_failure()
        logger.exception(
            "Failed to enqueue related team metadata fan-out",
            organization_id=organization_id,
            project_id=project_id,
            error=str(e),
        )


def _any_field_may_have_changed(update_fields: frozenset[str] | None, fields: frozenset[str]) -> bool:
    """Whether a save could have touched any of `fields`.

    A `None` update_fields means a full save, where we can't tell, so we assume it might have.
    """
    return update_fields is None or not fields.isdisjoint(update_fields)


def update_team_metadata_cache_on_save(sender: type[Team], instance: Team, created: bool, **kwargs: Any) -> None:
    """Update team metadata cache when a Team is saved."""
    if not settings.FLAGS_REDIS_URL:
        return

    _enqueue_team_metadata_update_on_commit(instance.id)


def update_team_metadata_cache_on_flag_policy_save(
    sender: type[TeamFeatureFlagPolicyConfig], instance: TeamFeatureFlagPolicyConfig, created: bool, **kwargs: Any
) -> None:
    """Refresh the cached team when its request blocklists change, because the flags service reads them from that cache."""
    if not settings.FLAGS_REDIS_URL:
        return
    # The first read of Team.feature_flag_policy_config creates an empty row, and the cache
    # already holds empty lists for a team without a row.
    if created and not instance.blocked_hosts and not instance.blocked_ips:
        return
    if not _any_field_may_have_changed(kwargs.get("update_fields"), frozenset({"blocked_hosts", "blocked_ips"})):
        return

    _enqueue_team_metadata_update_on_commit(instance.team_id)


def clear_team_metadata_cache_on_delete(sender: type[Team], instance: Team, **kwargs: Any) -> None:
    """Clear team metadata cache when a Team is deleted."""
    if not settings.FLAGS_REDIS_URL:
        return

    # NB: For unit tests, only clear Redis to avoid S3 timestamp issues with frozen time
    kinds = ["redis"] if settings.TEST else None
    clear_team_metadata_cache(instance, kinds=kinds)


# Organization and project names are denormalized into team metadata, but only the Team signal
# refreshes the cache. These receivers cover org/project renames, which never touch the Team row.
# Deletes need no receiver: both FKs cascade to Team, firing the Team pre_delete handler above.
def update_team_metadata_cache_on_organization_save(
    sender: type[Organization], instance: Organization, created: bool, **kwargs: Any
) -> None:
    """Refresh dependent team metadata caches when an organization is renamed."""
    if created or not settings.FLAGS_REDIS_URL:
        return
    if not _any_field_may_have_changed(kwargs.get("update_fields"), frozenset({"name"})):
        return

    transaction.on_commit(lambda: _enqueue_related_team_metadata_fanout(organization_id=instance.id))


def update_team_metadata_cache_on_project_save(
    sender: type[Project], instance: Project, created: bool, **kwargs: Any
) -> None:
    """Refresh dependent team metadata caches when a project is renamed."""
    if created or not settings.FLAGS_REDIS_URL:
        return
    if not _any_field_may_have_changed(kwargs.get("update_fields"), frozenset({"name"})):
        return

    transaction.on_commit(lambda: _enqueue_related_team_metadata_fanout(project_id=instance.id))


def connect_signal_handlers() -> None:
    post_save.connect(update_team_metadata_cache_on_save, sender=Team)
    post_save.connect(update_team_metadata_cache_on_flag_policy_save, sender=TeamFeatureFlagPolicyConfig)
    pre_delete.connect(clear_team_metadata_cache_on_delete, sender=Team)
    post_save.connect(update_team_metadata_cache_on_organization_save, sender=Organization)
    post_save.connect(update_team_metadata_cache_on_project_save, sender=Project)
