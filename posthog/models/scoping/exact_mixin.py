from __future__ import annotations

from django.db import models

from posthog.models.scoping.manager import ExactTeamScopedManager


class ExactTeamScopedMixin(models.Model):
    """Abstract base for fail-closed models owned by one exact team_id."""

    objects = ExactTeamScopedManager()

    class Meta:
        abstract = True


__all__ = ["ExactTeamScopedMixin"]
