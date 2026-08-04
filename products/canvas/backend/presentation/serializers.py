from typing import Any

from rest_framework import serializers

from posthog.api.shared import UserBasicSerializer

from products.canvas.backend.contract import canvas_sdk_version, contract_limits
from products.canvas.backend.models import Canvas

# Base64 expands 3 source bytes into 4 characters (padded); size the asset field
# from the contract's total-source cap rather than restating the number.
_MAX_ASSET_BASE64_LENGTH = (contract_limits()["maxSourceTotalBytes"] + 2) // 3 * 4


class CanvasSerializer(serializers.ModelSerializer):
    """A canvas document. Version/build content hangs off the source and build endpoints."""

    channel = serializers.UUIDField(source="channel_id", read_only=True)
    current_version_id = serializers.UUIDField(
        source="current_source_version_id",
        read_only=True,
        allow_null=True,
        help_text="Id of the live source version — pass as expected_current_version_id on publish. Null before the first publish.",
    )
    published_build_id = serializers.UUIDField(
        read_only=True,
        allow_null=True,
        help_text="Id of the canvas's live (last successful, still-eligible) build. Null until a build completes.",
    )
    created_by = UserBasicSerializer(read_only=True)
    pinned = serializers.SerializerMethodField(help_text="Whether the canvas is pinned to its channel.")

    class Meta:
        model = Canvas
        fields = [
            "id",
            "name",
            "channel",
            "template_id",
            "context",
            "generation_task_id",
            "pinned",
            "pinned_at",
            "current_version_id",
            "published_build_id",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_pinned(self, canvas: Canvas) -> bool:
        return canvas.pinned_at is not None


class CanvasCreateSerializer(serializers.Serializer):
    """Payload for creating a new, empty canvas in a channel."""

    name = serializers.CharField(
        allow_blank=False,
        trim_whitespace=True,
        max_length=400,
        help_text="Display name for the canvas.",
    )
    channel_id = serializers.UUIDField(help_text="Id of the channel the canvas belongs to.")
    template_id = serializers.CharField(
        required=False, default="freeform", max_length=64, help_text="Canvas template identifier."
    )


class CanvasUpdateSerializer(serializers.Serializer):
    """Writable canvas fields: metadata only — source changes go through publish/edit."""

    name = serializers.CharField(
        required=False,
        allow_blank=False,
        trim_whitespace=True,
        max_length=400,
        help_text="Updated display name.",
    )
    # The field name shadows BaseSerializer.context; the metaclass moves declared fields into
    # _declared_fields, so self.context still resolves to the serializer context at runtime.
    context = serializers.CharField(  # type: ignore[assignment]
        required=False, allow_blank=True, trim_whitespace=False, help_text="Updated author context markdown."
    )
    pinned = serializers.BooleanField(required=False, help_text="Whether the canvas is pinned in its channel.")
    generation_task_id = serializers.UUIDField(
        required=False, allow_null=True, help_text="Task currently generating this canvas, or null to clear it."
    )


class CanvasSourceAssetSerializer(serializers.Serializer):
    encoding = serializers.ChoiceField(choices=["base64"])
    contentType = serializers.ChoiceField(
        choices=[
            "image/png",
            "image/jpeg",
            "image/gif",
            "image/webp",
            "image/svg+xml",
            "font/woff",
            "font/woff2",
            "application/wasm",
            "application/octet-stream",
        ]
    )
    content = serializers.RegexField(
        regex=r"^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$",
        max_length=_MAX_ASSET_BASE64_LENGTH,
    )


class CanvasPostHogCapabilitiesSerializer(serializers.Serializer):
    insights = serializers.ListField(child=serializers.CharField(max_length=128), max_length=100)
    inlineQueries = serializers.BooleanField()
    captureEvents = serializers.ListField(child=serializers.CharField(max_length=200), max_length=100)


class CanvasNetworkCapabilitiesSerializer(serializers.Serializer):
    origins = serializers.ListField(child=serializers.URLField(max_length=2048), max_length=20)


class CanvasCapabilitiesSerializer(serializers.Serializer):
    posthog = CanvasPostHogCapabilitiesSerializer()
    network = CanvasNetworkCapabilitiesSerializer()


class CanvasSourceProjectSerializer(serializers.Serializer):
    """A canvas's multi-file source project — the canonical write format for canvas source."""

    schemaVersion = serializers.IntegerField(
        help_text="Source-project schema version. Currently always 1.",
    )
    files = serializers.DictField(
        child=serializers.CharField(allow_blank=True, trim_whitespace=False),
        help_text="Project files keyed by relative path (forward slashes, no '..').",
    )
    assets = serializers.DictField(
        child=CanvasSourceAssetSerializer(),
        required=False,
        default=dict,
        help_text="Optional base64-encoded binary assets keyed by safe project-relative paths.",
    )
    entryHtml = serializers.CharField(
        help_text='The project\'s entry HTML file. Currently always "index.html".',
    )
    dependencies = serializers.DictField(
        child=serializers.CharField(),
        required=False,
        default=dict,
        help_text=(
            "Exact-version dependencies, restricted to the platform-supported set (react, react-dom, "
            "@posthog/quill, recharts, lucide-react, dayjs) at their pinned versions."
        ),
    )
    canvasSdkVersion = serializers.CharField(
        required=False,
        default=canvas_sdk_version,
        help_text="Version of the host-injected `ph` canvas SDK the project targets.",
    )
    capabilities = CanvasCapabilitiesSerializer(
        required=False,
        default=lambda: {
            "posthog": {"insights": [], "inlineQueries": False, "captureEvents": []},
            "network": {"origins": []},
        },
        help_text=(
            "Bounded capabilities frozen into the built artifact. Declare every insight short id the "
            "canvas loads, every event it captures, and inlineQueries when it runs ad-hoc HogQL — the "
            "host enforces these at runtime and validation rejects undeclared `ph` calls."
        ),
    )


class CanvasDiagnosticSerializer(serializers.Serializer):
    """One structured validation/build diagnostic for a canvas source project."""

    severity = serializers.ChoiceField(
        choices=["error", "warning"],
        help_text="'error' blocks publishing; 'warning' is advisory and does not block.",
    )
    code = serializers.CharField(
        help_text="Stable machine-readable diagnostic code, e.g. 'import_not_allowed' or 'capability_missing_insight'.",
    )
    message = serializers.CharField(help_text="Human-readable description of the problem and how to fix it.")
    path = serializers.CharField(
        required=False,
        help_text="Project-relative path of the file the diagnostic points at, when file-specific.",
    )
    line = serializers.IntegerField(
        required=False,
        help_text="1-based line number within `path`, when the diagnostic points at a specific line.",
    )


class CanvasSummarySerializer(serializers.Serializer):
    """Identity and version pointers for one canvas."""

    id = serializers.UUIDField(help_text="The canvas's id.")
    name = serializers.CharField(help_text="Display name of the canvas.")
    channel_id = serializers.UUIDField(help_text="Id of the channel the canvas belongs to.")
    current_version_id = serializers.CharField(
        allow_null=True,
        source="current_source_version_id",
        help_text="Id of the live source version — pass as expected_current_version_id on publish. Null before the first publish.",
    )
    published_build_id = serializers.CharField(
        allow_null=True,
        help_text="Id of the canvas's live (last successful, still-eligible) build. Null until a build completes.",
    )
    created_at = serializers.DateTimeField(help_text="When the canvas was created.")


class CanvasVersionSerializer(serializers.Serializer):
    """One entry of a canvas's source-version history (metadata only —
    fetch a version's files via `source?version_id=`)."""

    id = serializers.UUIDField(help_text="The version's id.")
    parent_version_id = serializers.UUIDField(
        allow_null=True, help_text="The version this one was based on (null for the first publish)."
    )
    prompt = serializers.CharField(allow_null=True, help_text="Short description recorded with the publish.")
    task_id = serializers.UUIDField(allow_null=True, help_text="Task that published the version, when one did.")
    created_by = UserBasicSerializer(read_only=True, allow_null=True)
    created_at = serializers.DateTimeField(help_text="When the version was published.")


class CanvasSourceResponseSerializer(serializers.Serializer):
    """A canvas's source project plus the version pointer edits must be based on."""

    canvas = CanvasSummarySerializer(help_text="Identity and version pointers for the canvas.")
    project = CanvasSourceProjectSerializer(
        help_text="The canvas's source project. Pre-relational single-file canvases are presented as a synthetic project."
    )
    current_version_id = serializers.CharField(
        allow_null=True,
        help_text="The live source version this project reflects — pass as expected_current_version_id when publishing an edit. Null before the first publish.",
    )


class CanvasValidateRequestSerializer(serializers.Serializer):
    """Payload for validating a candidate source project without publishing it."""

    project = CanvasSourceProjectSerializer(help_text="The candidate source project to validate.")


class CanvasValidateResponseSerializer(serializers.Serializer):
    """Validation outcome for a candidate source project."""

    valid = serializers.BooleanField(help_text="True when the project has no error-severity diagnostics.")
    diagnostics = CanvasDiagnosticSerializer(
        many=True,
        help_text="Structured diagnostics; errors block publishing, warnings are advisory.",
    )


class CanvasSourcePublishSerializer(serializers.Serializer):
    """Payload for publishing a complete canvas source project."""

    project = CanvasSourceProjectSerializer(help_text="The complete source project to publish.")
    prompt = serializers.CharField(
        required=False,
        allow_blank=True,
        trim_whitespace=False,
        help_text="Short description of the change, stored on the appended version history entry.",
    )
    name = serializers.CharField(
        required=False,
        allow_blank=False,
        trim_whitespace=True,
        max_length=400,
        help_text="Optional new display name for the canvas.",
    )
    expected_current_version_id = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=False,
        help_text=(
            "Optimistic-concurrency guard: the current_version_id the publisher based its edits on "
            "(null when it read a canvas with no versions yet). When the canvas has since moved past it "
            "the publish is rejected with a 409 version_conflict instead of overwriting the newer head. "
            "Omit to publish unguarded."
        ),
    )


class CanvasSourceEditOperationSerializer(serializers.Serializer):
    """One per-file edit: set a file's content, or delete it."""

    path = serializers.CharField(
        help_text='Project-relative path of the file to write or delete (e.g. "src/canvas.tsx").'
    )
    content = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        trim_whitespace=False,
        help_text="The file's complete new content. Null (or omitted) deletes the file.",
    )


class CanvasSourceEditSerializer(serializers.Serializer):
    """Payload for publishing per-file edits against the canvas's current source."""

    operations = CanvasSourceEditOperationSerializer(
        many=True,
        allow_empty=False,
        help_text="Edits applied in order to the canvas's current source project.",
    )
    prompt = serializers.CharField(
        required=False,
        allow_blank=True,
        trim_whitespace=False,
        help_text="Short description of the change, stored on the appended version history entry.",
    )
    name = serializers.CharField(
        required=False,
        allow_blank=False,
        trim_whitespace=True,
        max_length=400,
        help_text="Optional new display name for the canvas.",
    )
    expected_current_version_id = serializers.CharField(
        allow_null=True,
        help_text=(
            "Required optimistic-concurrency guard: the current_version_id the edits are based on (null when the "
            "canvas has never been published). Diff edits against a moved head are rejected with 409 "
            "version_conflict — they cannot be published unguarded."
        ),
    )


class CanvasSourcePublishResponseSerializer(serializers.Serializer):
    """Result of a successful source-project publish."""

    canvas = CanvasSummarySerializer(help_text="The canvas after the publish, including the new version pointer.")
    current_version_id = serializers.CharField(help_text="Id of the source version this publish created.")
    diagnostics = CanvasDiagnosticSerializer(
        many=True,
        help_text="Advisory (warning-severity) diagnostics recorded for the published project.",
    )


class CanvasPublishConflictSerializer(serializers.Serializer):
    """409 body for a guarded canvas publish based on a stale version."""

    detail = serializers.CharField(help_text="Human-readable description of the conflict and how to recover.")
    code = serializers.CharField(help_text='Always "version_conflict".')
    current_version_id = serializers.CharField(
        allow_null=True,
        help_text="The canvas's live current_version_id at rejection time (null when the canvas has no versions).",
    )


class CanvasSourceInvalidSerializer(serializers.Serializer):
    """400 body for a publish whose source project failed validation."""

    detail = serializers.CharField(help_text="Human-readable summary of why the project was rejected.")
    code = serializers.CharField(help_text='Always "invalid_source_project".')
    diagnostics = CanvasDiagnosticSerializer(
        many=True,
        help_text="The validation diagnostics, including at least one error.",
    )


class CanvasArtifactAssetSerializer(serializers.Serializer):
    """One emitted file of a built canvas artifact."""

    path = serializers.CharField(help_text="Artifact-relative path of the emitted file.")
    contentHash = serializers.CharField(help_text="Hex SHA-256 of the file content.")
    sizeBytes = serializers.IntegerField(help_text="Size of the file in bytes.")


class CanvasArtifactManifestSerializer(serializers.Serializer):
    """The manifest frozen into a ready build: entry, assets, versions, capabilities."""

    entryHtml = serializers.CharField(help_text="The artifact's entry HTML file.")
    assets = CanvasArtifactAssetSerializer(many=True, help_text="Every emitted artifact file with its content hash.")
    dependencies = serializers.DictField(
        child=serializers.CharField(),
        help_text="Exact dependency versions the artifact was built against.",
    )
    canvasSdkVersion = serializers.CharField(help_text="Version of the `ph` canvas SDK the artifact targets.")
    legacyComponentPath = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Path of the runtime-mounted React component, for legacy-tier artifacts.",
    )
    legacyCode = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        trim_whitespace=False,
        help_text="The runtime-mounted component source, for legacy-tier artifacts.",
    )
    capabilities = serializers.DictField(
        help_text="Declared PostHog/network capabilities the artifact is held to at runtime.",
    )


class CanvasBuildSerializer(serializers.Serializer):
    """Lifecycle record of one build of a canvas source version."""

    id = serializers.UUIDField(help_text="The build's id.")
    source_version_id = serializers.UUIDField(help_text="The source version this build compiled.")
    build_status = serializers.ChoiceField(
        choices=["queued", "building", "ready", "failed"],
        source="status",
        help_text="Build lifecycle state. A failed build never replaces the last-known-good artifact.",
    )
    diagnostics = CanvasDiagnosticSerializer(
        many=True,
        help_text="Structured diagnostics recorded by the build (errors explain a failed status).",
    )
    manifest = CanvasArtifactManifestSerializer(
        required=False,
        allow_null=True,
        help_text="The frozen artifact manifest — present once the build is ready.",
    )
    integrity = serializers.CharField(
        allow_null=True,
        help_text="Hex SHA-256 over the manifest — the artifact's integrity anchor. Null until ready.",
    )
    artifact_url = serializers.SerializerMethodField(
        help_text="Signed URL for the ready build's entry HTML. Null until ready or when artifact delivery is unavailable.",
    )
    pinned = serializers.BooleanField(help_text="Pinned builds are retained for the lifetime of the canvas.")
    created_at = serializers.DateTimeField(help_text="When the build was queued.")
    finished_at = serializers.DateTimeField(allow_null=True, help_text="When the build reached a terminal state.")

    def get_artifact_url(self, build: Any) -> str | None:
        from products.canvas.backend.artifacts import create_canvas_artifact_url  # noqa: PLC0415

        # artifact_object_prefix is cleared by retention once a ready build's
        # objects are pruned; the artifact view 404s on it, so don't advertise a
        # URL that can't be served.
        if (
            build.status != build.STATUS_READY
            or not build.artifact_object_prefix
            or not isinstance(build.manifest, dict)
        ):
            return None
        entry = build.manifest.get("entryHtml")
        if not isinstance(entry, str):
            return None
        return create_canvas_artifact_url(build, entry)


class CanvasBuildsResponseSerializer(serializers.Serializer):
    """A canvas's build lifecycle: live pointers plus its most recent builds."""

    published_build_id = serializers.CharField(
        allow_null=True,
        help_text="Id of the canvas's live build (the last successful, still-eligible one). Null until a build completes.",
    )
    current_version_id = serializers.CharField(
        allow_null=True,
        help_text="Id of the source version the canvas's head points at.",
    )
    builds = CanvasBuildSerializer(
        many=True,
        help_text="Most recent builds, newest first (capped at 20; the live build is always included).",
    )


class CanvasBuildActionSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=["retry", "pin", "unpin", "cancel"])
    build_id = serializers.UUIDField()


class CanvasRevertSerializer(serializers.Serializer):
    """Payload for reverting the canvas's head to an existing source version."""

    version_id = serializers.UUIDField(help_text="Id of the source version to make the head again.")
    expected_current_version_id = serializers.UUIDField(
        allow_null=True, help_text="Current source version observed before requesting the revert."
    )
