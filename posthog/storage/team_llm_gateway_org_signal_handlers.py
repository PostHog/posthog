"""
Signal handlers that write a team's llm-gateway organization entry when PostHog creates the team or moves
its project to another organization, and clear a deleted team's.

Wired from PostHogConfig.ready() via connect_signal_handlers(). Changes to the organization's billing
values reach the entries from `BillingManager.update_org_details`, not from these handlers.
"""

from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_init, post_save, pre_delete

import structlog

from posthog.models.team import Team
from posthog.storage.team_llm_gateway_org_cache import clear_team_llm_gateway_org_cache

logger = structlog.get_logger(__name__)

# The organization a Team was loaded with, so post_save sees a move without a database read.
_LOADED_ORGANIZATION_ID_ATTR = "_llm_gateway_org_loaded_organization_id"


def _snapshot_organization(sender: type[Team], instance: Team, **kwargs: Any) -> None:
    # Read through __dict__ so a deferred organization_id never loads.
    if "organization_id" in instance.__dict__:
        instance.__dict__[_LOADED_ORGANIZATION_ID_ATTR] = instance.__dict__["organization_id"]


def _project_team(sender: type[Team], instance: Team, created: bool, **kwargs: Any) -> None:
    loaded = instance.__dict__.get(_LOADED_ORGANIZATION_ID_ATTR)
    current = instance.__dict__.get("organization_id")
    moved = not created and loaded is not None and current is not None and loaded != current
    if current is not None:
        instance.__dict__[_LOADED_ORGANIZATION_ID_ATTR] = current
    if not (created or moved) or not settings.AI_GATEWAY_REDIS_URL:
        return
    team_id = instance.id

    def enqueue_task() -> None:
        # Imported here because PostHogConfig.ready() wires this module before the task modules load.
        from posthog.tasks.team_llm_gateway_org import update_team_llm_gateway_org_cache_task  # noqa: PLC0415

        try:
            update_team_llm_gateway_org_cache_task.delay(team_id)
        except Exception as e:
            # warm_llm_gateway_org_cache writes a missing entry. A moved team's stale entry waits for the refresh.
            logger.exception("Failed to enqueue the llm-gateway organization entry", team_id=team_id, error=str(e))

    transaction.on_commit(enqueue_task)


def _clear_deleted_team(sender: type[Team], instance: Team, **kwargs: Any) -> None:
    if not settings.AI_GATEWAY_REDIS_URL:
        return
    clear_team_llm_gateway_org_cache(instance, kinds=["redis"])


def connect_signal_handlers() -> None:
    post_init.connect(_snapshot_organization, sender=Team, dispatch_uid="llm_gateway_org_snapshot_organization")
    post_save.connect(_project_team, sender=Team, dispatch_uid="llm_gateway_org_project_team")
    pre_delete.connect(_clear_deleted_team, sender=Team, dispatch_uid="llm_gateway_org_clear_deleted_team")
