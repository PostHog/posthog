from django.db import models

from posthog.dataclasses import frozen


class EntityRefStatus(models.TextChoices):
    ACTIVE = "active"
    DELETED = "deleted"
    # The id resolves to nothing: the target was hard-deleted or never existed.
    MISSING = "missing"
    ARCHIVED = "archived"
    # No resolver is registered for the entity type, so the target's state is unreadable.
    UNKNOWN = "unknown"


@frozen
class EntityRef:
    """A reference resolved for display, as the owning product describes the entity."""

    type: str
    id: str
    name: str = ""
    url: str = ""
    status: str = EntityRefStatus.UNKNOWN


@frozen
class Reference:
    """One reference from a source entity to a target entity, as the source's own data states it.

    A reference says nothing about whether the target exists or is still compatible. That is
    resolved at read time by looking at the target, so the write path stays a pure function of
    the source instance.
    """

    target_type: str
    target_id: str
    # Source-defined label for where the reference sits, e.g. "trigger_audience". Roles let the
    # UI say how an entity is used and let impact rules differ per usage.
    role: str
    # Location inside the source, e.g. "actions[a1b2].config.conditions[0]". Part of the identity
    # so that two occurrences of the same target in the same role are both kept.
    path: str = ""


@frozen
class SyncResult:
    added: int
    removed: int
