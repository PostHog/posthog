"""Base mixin for change-feed participation.

Inherit `ChangeFeedMixin` and set `change_feed_type` to make a model's
saves + deletes emit change-feed events automatically — no per-model
`register_change_feed` call. `change_feed.py` discovers every model that
inherits this and wires the signals on app start.

Caveat: events fire from `post_save` / `post_delete`, which Django does
NOT emit for `QuerySet.update()` / `bulk_update()` / `bulk_create()`. A
fed model mutated that way won't publish — use `.save()` / `.delete()`
or publish manually via `publish_change`.

Lives in its own module (no imports beyond Django) so `models.py` can
inherit it and `change_feed.py` can import it for discovery without a
circular import.
"""

from __future__ import annotations

from django.db import models


class ChangeFeedMixin(models.Model):
    class Meta:
        abstract = True

    # Subclasses opt in by setting this to the entity type the console keys
    # queries on (e.g. "agent_application"). Empty = not fed.
    change_feed_type: str = ""

    @property
    def change_feed_team_id(self) -> int | None:
        """Owning team. Override when team isn't a direct `team_id` attr."""
        return getattr(self, "team_id", None)
