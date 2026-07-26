from __future__ import annotations

import re
import json
import hashlib
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from rest_framework import serializers

from posthog.api.canvas_artifacts import create_canvas_artifact_token
from posthog.models.file_system.canvas import (
    CanvasApplication,
    CanvasBuild,
    CanvasSourceVersion,
    serialize_canvas_project,
)
from posthog.models.file_system.file_system import FileSystem
from posthog.storage import object_storage
from posthog.tasks.canvas_builds import build_canvas

from products.tasks.backend.facade import api as tasks_facade

CANVAS_MAX_FILES = 128
CANVAS_MAX_FILE_BYTES = 1_000_000
CANVAS_MAX_SOURCE_BYTES = 5_000_000
CANVAS_MAX_DIAGNOSTICS = 500
CANVAS_MAX_DEPENDENCIES = 64
CANVAS_SDK_VERSION = "1.0.0"
ADMITTED_DEPENDENCIES = {
    "@posthog/quill": "0.3.0-beta.24",
    "react": "19.2.6",
    "react-dom": "19.2.6",
    "three": "0.183.2",
}
PACKAGE_NAME = re.compile(r"^(?:@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*$")
EXACT_VERSION = re.compile(
    r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)


class StrictSerializer(serializers.Serializer):
    def to_internal_value(self, data: Any) -> dict[str, Any]:
        if isinstance(data, dict):
            unknown = set(data) - set(self.fields)
            if unknown:
                raise serializers.ValidationError(dict.fromkeys(sorted(unknown), "Unknown field."))
        return super().to_internal_value(data)


class CanvasPostHogCapabilitiesSerializer(StrictSerializer):
    insights = serializers.ListField(
        child=serializers.CharField(min_length=1, max_length=128),
        max_length=256,
        help_text="Insight short IDs that this canvas may load.",
    )
    inlineQueries = serializers.BooleanField(help_text="Whether this canvas may execute inline PostHog queries.")
    captureEvents = serializers.ListField(
        child=serializers.CharField(min_length=1, max_length=200),
        max_length=256,
        help_text="Event names that this canvas may capture.",
    )

    def validate_insights(self, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))

    def validate_captureEvents(self, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


class CanvasNetworkCapabilitiesSerializer(StrictSerializer):
    origins = serializers.ListField(
        child=serializers.CharField(max_length=2048),
        max_length=64,
        help_text="HTTPS origins that the canvas may contact directly.",
    )

    def validate_origins(self, value: list[str]) -> list[str]:
        for origin in value:
            parsed = urlparse(origin)
            if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
                raise serializers.ValidationError("Each network capability must be an HTTPS origin.")
            if origin != f"{parsed.scheme}://{parsed.netloc}":
                raise serializers.ValidationError("Network capabilities must not include paths, queries, or fragments.")
        if value:
            raise serializers.ValidationError(
                "External network access is unavailable until canvas capability approval is implemented."
            )
        return list(dict.fromkeys(value))


class CanvasCapabilitiesSerializer(StrictSerializer):
    posthog = CanvasPostHogCapabilitiesSerializer(help_text="PostHog data and capture capabilities.")
    network = CanvasNetworkCapabilitiesSerializer(help_text="Direct network capabilities.")


class CanvasSourceProjectSerializer(StrictSerializer):
    schemaVersion = serializers.IntegerField(min_value=1, max_value=1, help_text="Canvas source schema version.")
    files = serializers.DictField(
        child=serializers.CharField(trim_whitespace=False, allow_blank=True),
        help_text="Complete map of normalized project-relative paths to UTF-8 source files.",
    )
    entryHtml = serializers.CharField(help_text='HTML entry file. Must be "index.html".')
    dependencies = serializers.DictField(
        child=serializers.CharField(),
        help_text="Browser package names mapped to exact admitted semantic versions.",
    )
    canvasSdkVersion = serializers.CharField(help_text="Exact canvas runtime SDK version.")
    capabilities = CanvasCapabilitiesSerializer(help_text="Capabilities enforced by the build and runtime.")

    def validate_files(self, files: dict[str, str]) -> dict[str, str]:
        if len(files) > CANVAS_MAX_FILES:
            raise serializers.ValidationError(f"A canvas may contain at most {CANVAS_MAX_FILES} files.")
        total = 0
        for path, content in files.items():
            if not isinstance(path, str) or not path or len(path) > 240:
                raise serializers.ValidationError("Source paths must be non-empty strings of at most 240 characters.")
            segments = path.split("/")
            if (
                path.startswith("/")
                or "\\" in path
                or any(ord(character) < 32 or ord(character) == 127 for character in path)
                or any(segment in {"", ".", ".."} for segment in segments)
            ):
                raise serializers.ValidationError("Source paths must be normalized project-relative paths.")
            size = len(content.encode())
            if size > CANVAS_MAX_FILE_BYTES:
                raise serializers.ValidationError(
                    f"Each canvas file may contain at most {CANVAS_MAX_FILE_BYTES} bytes."
                )
            total += size
        if total > CANVAS_MAX_SOURCE_BYTES:
            raise serializers.ValidationError(f"Canvas source may contain at most {CANVAS_MAX_SOURCE_BYTES} bytes.")
        return files

    def validate_dependencies(self, dependencies: dict[str, str]) -> dict[str, str]:
        if len(dependencies) > CANVAS_MAX_DEPENDENCIES:
            raise serializers.ValidationError(f"A canvas may declare at most {CANVAS_MAX_DEPENDENCIES} dependencies.")
        for name, version in dependencies.items():
            if len(name) > 214 or not PACKAGE_NAME.fullmatch(name):
                raise serializers.ValidationError(f'Invalid package name: "{name}".')
            if len(version) > 100 or not EXACT_VERSION.fullmatch(version):
                raise serializers.ValidationError(f'Package "{name}" must use an exact semantic version.')
            if ADMITTED_DEPENDENCIES.get(name) != version:
                raise serializers.ValidationError(
                    f'Package "{name}" at {version} is not available in the canvas build environment.'
                )
        return dependencies

    def validate_canvasSdkVersion(self, value: str) -> str:
        if not EXACT_VERSION.fullmatch(value):
            raise serializers.ValidationError("The canvas SDK must use an exact semantic version.")
        if value != CANVAS_SDK_VERSION:
            raise serializers.ValidationError(f"Canvas SDK version {value} is not supported.")
        return value

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        attrs = super().validate(attrs)
        if attrs["entryHtml"] != "index.html":
            raise serializers.ValidationError({"entryHtml": 'The canvas entry file must be "index.html".'})
        if attrs["entryHtml"] not in attrs["files"]:
            raise serializers.ValidationError({"entryHtml": "The canvas entry file is missing from files."})
        serialized_size = len(json.dumps(attrs, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode())
        if serialized_size > CANVAS_MAX_SOURCE_BYTES:
            raise serializers.ValidationError(f"Canvas source may contain at most {CANVAS_MAX_SOURCE_BYTES} bytes.")
        return attrs


class CanvasPublishRequestSerializer(StrictSerializer):
    project = CanvasSourceProjectSerializer(help_text="Complete canvas source project to publish.")
    expectedCurrentVersionId = serializers.UUIDField(
        allow_null=True,
        help_text="Current source version that this edit is based on. Pass null for the first version.",
    )
    taskId = serializers.UUIDField(
        required=False,
        help_text="Task that produced this source version. Sandbox tasks are attributed automatically.",
    )
    taskRunId = serializers.UUIDField(
        required=False,
        help_text="Fresh task run that produced this source version. Sandbox tasks are attributed automatically.",
    )
    prompt = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=10_000,
        trim_whitespace=False,
        help_text="Short description of the requested canvas change.",
    )


class CanvasApplicationConflictSerializer(StrictSerializer):
    code = serializers.CharField(read_only=True, help_text='Always "version_conflict".')
    detail = serializers.CharField(read_only=True, help_text="How to recover from the conflicting edit.")
    currentVersionId = serializers.UUIDField(
        allow_null=True, read_only=True, help_text="Current source version that rejected the stale edit."
    )


class CanvasDiagnosticSerializer(StrictSerializer):
    severity = serializers.ChoiceField(choices=["error", "warning", "info"], help_text="Diagnostic severity.")
    code = serializers.CharField(max_length=100, help_text="Stable diagnostic code.")
    message = serializers.CharField(max_length=10_000, help_text="Build diagnostic message.")
    file = serializers.CharField(required=False, help_text="Project-relative source file.")
    line = serializers.IntegerField(required=False, min_value=1, help_text="One-based source line.")
    column = serializers.IntegerField(required=False, min_value=0, help_text="Zero-based source column.")


class CanvasArtifactFileSerializer(StrictSerializer):
    path = serializers.CharField(read_only=True, help_text="Normalized artifact path relative to this build.")
    contentType = serializers.CharField(read_only=True, help_text="HTTP content type for this artifact file.")
    bytes = serializers.IntegerField(read_only=True, min_value=0, help_text="UTF-8 artifact size in bytes.")
    sha256 = serializers.RegexField(
        regex=r"^[a-f0-9]{64}$", read_only=True, help_text="Lowercase SHA-256 digest of the artifact content."
    )


class CanvasArtifactManifestSerializer(StrictSerializer):
    schemaVersion = serializers.IntegerField(read_only=True, help_text="Artifact manifest schema version.")
    entryHtml = serializers.CharField(read_only=True, help_text="HTML entry file for this artifact.")
    files = CanvasArtifactFileSerializer(many=True, read_only=True, help_text="Immutable emitted artifact files.")
    canvasSdkVersion = serializers.CharField(read_only=True, help_text="Canvas runtime SDK version used by this build.")
    dependencies = serializers.DictField(
        child=serializers.CharField(), read_only=True, help_text="Exact package versions included in this build."
    )
    capabilities = CanvasCapabilitiesSerializer(read_only=True, help_text="Capabilities enforced for this artifact.")


class CanvasSourceVersionSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(read_only=True, help_text="Immutable source version ID.")
    parentVersionId = serializers.UUIDField(
        source="parent_version_id",
        allow_null=True,
        read_only=True,
        help_text="Source version edited to create this version.",
    )
    taskId = serializers.UUIDField(source="task_id", read_only=True, help_text="Task that produced this version.")
    taskRunId = serializers.UUIDField(
        source="task_run_id", read_only=True, help_text="Fresh task run that produced this version."
    )
    sourceHash = serializers.CharField(
        source="source_hash", read_only=True, help_text="Canonical source SHA-256 digest."
    )
    sourceSize = serializers.IntegerField(
        source="source_size", read_only=True, help_text="Canonical source size in bytes."
    )
    prompt = serializers.CharField(
        allow_null=True, read_only=True, help_text="Description of the requested canvas change."
    )
    createdAt = serializers.SerializerMethodField(help_text="Creation time as Unix milliseconds.")

    class Meta:
        model = CanvasSourceVersion
        fields = ["id", "parentVersionId", "taskId", "taskRunId", "sourceHash", "sourceSize", "prompt", "createdAt"]

    def get_createdAt(self, instance: CanvasSourceVersion) -> int:
        return int(instance.created_at.timestamp() * 1000)


class CanvasBuildSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(read_only=True, help_text="Immutable cloud build ID.")
    sourceVersionId = serializers.UUIDField(
        source="source_version_id", read_only=True, help_text="Source version compiled by this build."
    )
    status = serializers.ChoiceField(
        source="build_status",
        choices=CanvasBuild.Status.choices,
        read_only=True,
        help_text="Current build lifecycle status.",
    )
    artifactUrl = serializers.SerializerMethodField(help_text="Short-lived URL for the immutable artifact entry HTML.")
    integrity = serializers.CharField(
        allow_null=True, read_only=True, help_text="SHA-256 integrity value for entry HTML."
    )
    diagnostics = CanvasDiagnosticSerializer(many=True, read_only=True, help_text="Bounded build diagnostics.")
    manifest = CanvasArtifactManifestSerializer(
        allow_null=True, read_only=True, help_text="Immutable artifact and capability manifest when ready."
    )
    createdAt = serializers.SerializerMethodField(help_text="Build creation time as Unix milliseconds.")
    completedAt = serializers.SerializerMethodField(
        help_text="Build completion time as Unix milliseconds, if complete."
    )

    class Meta:
        model = CanvasBuild
        fields = [
            "id",
            "sourceVersionId",
            "status",
            "artifactUrl",
            "integrity",
            "diagnostics",
            "manifest",
            "createdAt",
            "completedAt",
        ]

    def get_artifactUrl(self, instance: CanvasBuild) -> str | None:
        if instance.build_status != CanvasBuild.Status.READY or not instance.artifact_object_prefix:
            return None
        request = self.context.get("request")
        token = create_canvas_artifact_token(instance)
        if request is None or token is None:
            return None
        path = f"/canvas-artifacts/{token}/index.html"
        return (
            f"{settings.CANVAS_ARTIFACT_ORIGIN}{path}"
            if settings.CANVAS_ARTIFACT_ORIGIN
            else request.build_absolute_uri(path)
        )

    def get_createdAt(self, instance: CanvasBuild) -> int:
        return int(instance.created_at.timestamp() * 1000)

    def get_completedAt(self, instance: CanvasBuild) -> int | None:
        return int(instance.completed_at.timestamp() * 1000) if instance.completed_at else None


class CanvasSourceSnapshotSerializer(StrictSerializer):
    version = CanvasSourceVersionSerializer(read_only=True, help_text="Current immutable source version metadata.")
    project = CanvasSourceProjectSerializer(read_only=True, help_text="Complete current source project.")


class CanvasPublishResponseSerializer(StrictSerializer):
    version = CanvasSourceVersionSerializer(read_only=True, help_text="Published immutable source version metadata.")
    build = CanvasBuildSerializer(read_only=True, help_text="Queued authoritative cloud build.")


class CanvasValidationResponseSerializer(StrictSerializer):
    ok = serializers.BooleanField(read_only=True, help_text="Whether the candidate produced a valid artifact.")
    diagnostics = CanvasDiagnosticSerializer(many=True, read_only=True, help_text="Structured validation diagnostics.")
    manifest = CanvasArtifactManifestSerializer(
        allow_null=True, read_only=True, help_text="Validated candidate manifest when successful."
    )


class CanvasHistorySerializer(StrictSerializer):
    currentSourceVersionId = serializers.UUIDField(
        allow_null=True, read_only=True, help_text="Current source version for this canvas."
    )
    activeBuildId = serializers.UUIDField(
        allow_null=True, read_only=True, help_text="Last-known-good build currently displayed by this canvas."
    )
    versions = CanvasSourceVersionSerializer(many=True, read_only=True, help_text="Source versions in creation order.")
    builds = CanvasBuildSerializer(many=True, read_only=True, help_text="Build attempts in creation order.")


def validate_task_run_provenance(*, task_id: UUID, task_run_id: UUID, team_id: int, user_id: int | None) -> None:
    run = tasks_facade.get_task_run(task_run_id, team_id=team_id)
    if run is None or run.task_id != task_id or run.created_by_id != user_id:
        raise serializers.ValidationError({"taskRunId": "The task run does not match this task, project, and user."})


def publish_canvas_source(
    *, canvas: FileSystem, payload: dict[str, Any], user_id: int | None
) -> tuple[CanvasSourceVersion, CanvasBuild]:
    validate_task_run_provenance(
        task_id=payload["taskId"],
        task_run_id=payload["taskRunId"],
        team_id=canvas.team_id,
        user_id=user_id,
    )
    canonical, archive = serialize_canvas_project(payload["project"])
    source_hash = hashlib.sha256(canonical).hexdigest()
    object_key = f"canvas/source/{canvas.team_id}/sha256/{source_hash}.json.gz"
    object_storage.write(object_key, archive, extras={"ContentType": "application/gzip"})

    with transaction.atomic():
        locked_canvas = FileSystem.objects.select_for_update().get(id=canvas.id, team_id=canvas.team_id)
        application, _ = CanvasApplication.objects.for_team(canvas.team_id).get_or_create(
            team_id=canvas.team_id,
            canvas_id=canvas.id,
        )
        application = CanvasApplication.objects.for_team(canvas.team_id).select_for_update().get(id=application.id)
        current_id = application.current_source_version_id
        if current_id != payload["expectedCurrentVersionId"]:
            raise CanvasVersionConflict(current_id)
        try:
            version = CanvasSourceVersion.objects.for_team(canvas.team_id).create(
                team_id=canvas.team_id,
                canvas_id=canvas.id,
                parent_version_id=current_id,
                task_id=payload["taskId"],
                task_run_id=payload["taskRunId"],
                source_hash=source_hash,
                source_object_key=object_key,
                source_size=len(canonical),
                prompt=payload.get("prompt") or None,
                created_by_id=user_id,
            )
        except IntegrityError as error:
            raise serializers.ValidationError(
                {"taskRunId": "This task run has already published a canvas version."}
            ) from error
        build = CanvasBuild.objects.for_team(canvas.team_id).create(
            team_id=canvas.team_id,
            canvas_id=canvas.id,
            source_version=version,
        )
        application.current_source_version = version
        application.save(update_fields=["current_source_version", "updated_at"])
        meta = dict(locked_canvas.meta or {})
        meta.update({"kind": "freeform", "currentSourceVersionId": str(version.id)})
        locked_canvas.meta = meta
        locked_canvas.save(update_fields=["meta"])

        transaction.on_commit(lambda: build_canvas.delay(str(build.id), canvas.team_id))
    return version, build


class CanvasVersionConflict(Exception):
    def __init__(self, current_version_id: UUID | None):
        self.current_version_id = current_version_id
        super().__init__("Canvas source version conflict")


def current_canvas_source(canvas: FileSystem) -> tuple[CanvasSourceVersion, dict[str, Any]] | None:
    application = CanvasApplication.objects.for_team(canvas.team_id).filter(canvas_id=canvas.id).first()
    if application is None or application.current_source_version_id is None:
        return None
    version = CanvasSourceVersion.objects.for_team(canvas.team_id).get(id=application.current_source_version_id)
    return version, version.read_project()


def canvas_history(canvas: FileSystem) -> tuple[CanvasApplication | None, list[CanvasSourceVersion], list[CanvasBuild]]:
    application = CanvasApplication.objects.for_team(canvas.team_id).filter(canvas_id=canvas.id).first()
    versions = list(
        CanvasSourceVersion.objects.for_team(canvas.team_id).filter(canvas_id=canvas.id).order_by("created_at")
    )
    builds = list(CanvasBuild.objects.for_team(canvas.team_id).filter(canvas_id=canvas.id).order_by("created_at"))
    return application, versions, builds


def mark_build_failed(build: CanvasBuild, diagnostics: list[dict[str, Any]]) -> None:
    build.build_status = CanvasBuild.Status.FAILED
    build.diagnostics = diagnostics[:CANVAS_MAX_DIAGNOSTICS]
    build.completed_at = timezone.now()
    build.save(update_fields=["build_status", "diagnostics", "completed_at"])
