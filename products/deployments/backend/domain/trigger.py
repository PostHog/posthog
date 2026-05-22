"""Deployment trigger kinds — mirrored from the model's TextChoices.

Pure Python so non-Django callers (Temporal activities, the build runner
input contract) can import without dragging Django in.
"""

from __future__ import annotations

from enum import StrEnum


class TriggerKind(StrEnum):
    MANUAL = "manual"
    GIT = "git"
    REDEPLOY = "redeploy"
    ROLLBACK = "rollback"
    SEED = "seed"


class ErrorStep(StrEnum):
    DISPATCH = "dispatch"
    CLONE = "clone"
    INSTALL = "install"
    BUILD = "build"
    PUBLISH = "publish"
