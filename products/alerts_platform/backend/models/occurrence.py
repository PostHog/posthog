"""The platform's registry of identities a project has seen, for sources with no detection of their own.

Appearance alerts read it to tell a new identity from a known one. It is per project and per source,
not per alert, so two alerts on one source agree on what is new.
"""

from django.db import models
from django.utils import timezone

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel

from products.alerts_platform.backend.models.platform_alert import source_kind_choices


class PlatformOccurrence(TeamScopedRootMixin, UUIDModel):
    """One identity a source's feed reported for a project."""

    # The unique constraint leads with the team, so it serves the lookups an index on the team would.
    team = models.ForeignKey(
        "posthog.Team", on_delete=models.CASCADE, db_constraint=False, db_index=False, related_name="+"
    )
    source_kind = models.CharField(max_length=32, choices=source_kind_choices)
    identity_key = models.CharField(max_length=255)

    first_seen_at = models.DateTimeField()
    # Set by a person. A later sighting clears it and sets `reappeared_at`, which announces the identity again.
    resolved_at = models.DateTimeField(null=True, blank=True)
    # When the registry last recorded a fact about the identity. A check reads by this, not by when the
    # fact occurred, so a fact pushed late is still read.
    recorded_at = models.DateTimeField(default=timezone.now)
    reappeared_at = models.DateTimeField(null=True, blank=True)

    labels = models.JSONField(default=dict, db_default={})
    detail = models.JSONField(default=dict, db_default={})

    class Meta:
        db_table = "alerts_platformoccurrence"
        constraints = [
            models.UniqueConstraint(
                fields=["team", "source_kind", "identity_key"], name="platform_occurrence_one_per_identity"
            )
        ]
        indexes = [
            models.Index(fields=["team", "source_kind", "recorded_at"], name="platform_occurrence_rec_idx"),
        ]


class PlatformOccurrenceCursor(TeamScopedRootMixin, UUIDModel):
    """How far the registrar has read one source's feed for one project.

    Locked while the registrar records a read, so two runs never record the same window twice.
    """

    # The unique constraint leads with the team, so it serves the lookups an index on the team would.
    team = models.ForeignKey(
        "posthog.Team", on_delete=models.CASCADE, db_constraint=False, db_index=False, related_name="+"
    )
    source_kind = models.CharField(max_length=32, choices=source_kind_choices)
    registered_until = models.DateTimeField(null=True, blank=True)
    # The span the next read asks the feed for, shortened after a read the feed could not finish.
    read_span = models.DurationField(null=True, blank=True)

    class Meta:
        db_table = "alerts_platformoccurrencecursor"
        constraints = [
            models.UniqueConstraint(fields=["team", "source_kind"], name="platform_occurrence_cursor_one_per_source")
        ]
