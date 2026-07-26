from __future__ import annotations

import gzip
import json
from typing import Any

from django.db import models
from django.utils import timezone

from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.utils import UUIDModel, uuid7
from posthog.storage import object_storage


class CanvasApplication(TeamScopedRootMixin, UUIDModel):
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    canvas = models.OneToOneField(
        "posthog.FileSystem",
        on_delete=models.CASCADE,
        related_name="canvas_application",
        db_constraint=False,
    )
    current_source_version = models.ForeignKey(
        "posthog.CanvasSourceVersion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="current_for_applications",
        db_constraint=False,
    )
    active_build = models.ForeignKey(
        "posthog.CanvasBuild",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="active_for_applications",
        db_constraint=False,
    )
    previous_build = models.ForeignKey(
        "posthog.CanvasBuild",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="previous_for_applications",
        db_constraint=False,
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)


class CanvasSourceVersion(TeamScopedRootMixin):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    canvas = models.ForeignKey(
        "posthog.FileSystem",
        on_delete=models.CASCADE,
        related_name="canvas_source_versions",
        db_constraint=False,
    )
    parent_version = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="child_versions",
    )
    task_id = models.UUIDField()
    task_run_id = models.UUIDField()
    source_hash = models.CharField(max_length=64)
    source_object_key = models.CharField(max_length=500)
    source_size = models.PositiveIntegerField()
    prompt = models.TextField(null=True, blank=True)
    created_by_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["canvas", "task_run_id"], name="canvas_source_unique_run"),
        ]
        indexes = [
            models.Index(fields=["team", "canvas", "created_at"], name="canvas_source_history_idx"),
            models.Index(fields=["team", "source_hash"], name="canvas_source_hash_idx"),
        ]

    def read_project(self) -> dict[str, Any]:
        content = object_storage.read_bytes(self.source_object_key)
        if content is None:
            raise FileNotFoundError(self.source_object_key)
        project = json.loads(gzip.decompress(content))
        if not isinstance(project, dict):
            raise ValueError("Canvas source archive does not contain an object")
        return project


class CanvasBuild(TeamScopedRootMixin):
    class Status(models.TextChoices):
        QUEUED = "queued"
        BUILDING = "building"
        READY = "ready"
        FAILED = "failed"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False)
    canvas = models.ForeignKey(
        "posthog.FileSystem",
        on_delete=models.CASCADE,
        related_name="canvas_builds",
        db_constraint=False,
    )
    source_version = models.ForeignKey(
        CanvasSourceVersion,
        on_delete=models.CASCADE,
        related_name="builds",
    )
    build_status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED)
    artifact_object_prefix = models.CharField(max_length=500, null=True, blank=True)
    integrity = models.CharField(max_length=100, null=True, blank=True)
    diagnostics = models.JSONField(default=list)
    manifest = models.JSONField(null=True, blank=True)
    pinned = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["team", "canvas", "created_at"], name="canvas_build_history_idx"),
            models.Index(fields=["build_status", "completed_at"], name="canvas_build_retention_idx"),
        ]


def serialize_canvas_project(project: dict[str, Any]) -> tuple[bytes, bytes]:
    canonical = json.dumps(project, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return canonical, gzip.compress(canonical, mtime=0)
