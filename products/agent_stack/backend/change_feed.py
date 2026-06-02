"""Team-scoped change feed for agent-platform entities.

Every registered model emits a tiny `{type, team_id, id, op}` event on
save/delete to the per-team Redis channel `agent_changes:{team_id}`. The
agent-ingress (the streaming tier) fans these out to browsers as SSE; the
console maps each event to a query-key invalidation, so any view keyed to
that entity type re-derives from truth. Django only publishes — it never
holds the connection.

Adding reactivity for a new entity is one line: `register_change_feed(...)`.
That's the whole point — live updates are a property of the platform, not
something each new feature has to re-wire. Best-effort: a failed publish
never blocks the mutation; the durable truth is Postgres and a missed
event self-heals on the next read.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable

from django.apps import apps
from django.db.models import Model
from django.db.models.signals import post_delete, post_save

from posthog.redis import get_client

from .change_feed_base import ChangeFeedMixin

logger = logging.getLogger(__name__)

# Keep receiver references alive — Django connects signals weakly by default,
# so module-local closures would be garbage-collected and silently stop firing.
_receivers: list[Callable] = []


def agent_changes_channel(team_id: int) -> str:
    return f"agent_changes:{team_id}"


def publish_change(team_id: int | None, type_name: str, entity_id: str, op: str) -> None:
    """Fire-and-forget notification that an entity changed. Never raises.

    `op` is `created` / `updated` / `deleted`. `team_id` None (e.g. a
    canonical, team-less template) is skipped — the feed is team-scoped.
    """
    if team_id is None:
        return
    payload = json.dumps({"type": type_name, "team_id": team_id, "id": str(entity_id), "op": op})
    try:
        get_client().publish(agent_changes_channel(team_id), payload)
    except Exception:
        logger.exception("change feed: publish failed (team=%s type=%s id=%s op=%s)", team_id, type_name, entity_id, op)


def register_change_feed(
    model: type[Model],
    *,
    type_name: str,
    get_team_id: Callable[[Model], int | None] = lambda i: i.team_id,
) -> None:
    """Wire a model into the change feed: publish on every save + delete.

    `type_name` is the entity type the console keys queries on (e.g.
    `agent_application`). `get_team_id` extracts the owning team — defaults
    to a `team_id` attribute; pass a lambda for models scoped via a FK.
    """

    def on_save(sender: type, instance: Model, created: bool, **kwargs: object) -> None:
        try:
            publish_change(get_team_id(instance), type_name, str(instance.pk), "created" if created else "updated")
        except Exception:
            logger.exception("change feed: on_save failed for %s", type_name)

    def on_delete(sender: type, instance: Model, **kwargs: object) -> None:
        try:
            publish_change(get_team_id(instance), type_name, str(instance.pk), "deleted")
        except Exception:
            logger.exception("change feed: on_delete failed for %s", type_name)

    post_save.connect(on_save, sender=model, weak=False)
    post_delete.connect(on_delete, sender=model, weak=False)
    _receivers.extend([on_save, on_delete])


def _autoregister_change_feed_models() -> None:
    """Wire every `ChangeFeedMixin` model into the feed. New entity →
    inherit the mixin + set `change_feed_type` → live updates, zero wiring
    here. Runs once from `apps.ready()` (registry is populated by then)."""
    for model in apps.get_models():
        type_name = getattr(model, "change_feed_type", "")
        if type_name and issubclass(model, ChangeFeedMixin):
            register_change_feed(model, type_name=type_name, get_team_id=lambda i: i.change_feed_team_id)


_autoregister_change_feed_models()
