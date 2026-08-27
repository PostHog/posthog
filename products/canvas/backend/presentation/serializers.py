from typing import Any

from django.conf import settings

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from posthog.api.shared import UserBasicSerializer

from products.canvas.backend.contract import (
    GRID_COLUMN_CHOICES,
    MAX_COMPONENT_HEIGHT,
    MAX_COMPONENT_WIDTH,
    canvas_sdk_version,
    contract_limits,
)
from products.canvas.backend.facade.api import (
    CANVAS_LAYOUT_SCHEMA_VERSION,
    MAX_LAYOUT_PATCH_OPERATIONS,
    PLACEMENT_ID_RE,
    PLACEMENT_STATUSES,
    RESERVED_TEMPLATE_IDS,
)
from products.canvas.backend.models import Canvas, CanvasState

# Base64 expands 3 source bytes into 4 characters (padded); size the asset field
# from the contract's total-source cap rather than restating the number.
_MAX_ASSET_BASE64_LENGTH = (contract_limits()["maxSourceTotalBytes"] + 2) // 3 * 4

_CANVAS_URL_HELP_TEXT = (
    "Canonical link to the canvas in the PostHog app. The only valid way to link to a canvas — "
    "share this when pointing a user at it; never construct a canvas URL."
)


def canvas_url(canvas: Canvas) -> str:
    # The same shape the thread-message announcements use; the route deep-links
    # into the desktop app and renders in the web app.
    return f"{settings.SITE_URL}/code/canvas/{canvas.channel_id}/{canvas.id}"


class CanvasComponentSizeSerializer(serializers.Serializer):
    """A component's grid-size contract, in grid units."""

    defaultW = serializers.IntegerField(
        min_value=1, max_value=MAX_COMPONENT_WIDTH, help_text="Width a new placement starts at, in grid columns."
    )
    defaultH = serializers.IntegerField(
        min_value=1, max_value=MAX_COMPONENT_HEIGHT, help_text="Height a new placement starts at, in grid rows."
    )
    minW = serializers.IntegerField(
        min_value=1, max_value=MAX_COMPONENT_WIDTH, help_text="Narrowest width the component renders usefully at."
    )
    minH = serializers.IntegerField(
        min_value=1, max_value=MAX_COMPONENT_HEIGHT, help_text="Shortest height the component renders usefully at."
    )
    maxW = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=MAX_COMPONENT_WIDTH,
        help_text="Widest allowed width; omit for no cap below the grid's width.",
    )
    maxH = serializers.IntegerField(
        required=False,
        min_value=1,
        max_value=MAX_COMPONENT_HEIGHT,
        help_text="Tallest allowed height; omit for no cap.",
    )


class CanvasComponentMetaSerializer(serializers.Serializer):
    """A component's placement contract: how grid canvases may place and configure it."""

    size = CanvasComponentSizeSerializer(help_text="Grid-size contract for placements of this component.")
    configSchema = serializers.DictField(
        required=False,
        help_text=(
            'JSON Schema ("type": "object") for a placement\'s config. The host validates each '
            "placement's config against it and passes the validated object to the widget at mount."
        ),
    )


class CanvasSerializer(serializers.ModelSerializer):
    """A canvas document. Version/build content hangs off the source and build endpoints."""

    channel = serializers.UUIDField(source="channel_id", read_only=True)
    kind = serializers.ChoiceField(
        choices=Canvas.KINDS,
        read_only=True,
        help_text=(
            "What the canvas is: 'freeform' (a standalone app), 'component' (a reusable widget grids place), "
            "or 'grid' (a composition of components)."
        ),
    )
    description = serializers.CharField(
        read_only=True,
        help_text="Short prose describing the canvas. For components, the store-search text.",
    )
    component_meta = serializers.SerializerMethodField(
        help_text=(
            "For component-kind canvases: the head version's placement contract "
            "(size, optional configSchema). Null for other kinds and unpublished components."
        ),
    )
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
    url = serializers.SerializerMethodField(help_text=_CANVAS_URL_HELP_TEXT)

    class Meta:
        model = Canvas
        fields = [
            "id",
            "name",
            "kind",
            "description",
            "channel",
            "template_id",
            "context",
            "generation_task_id",
            "pinned",
            "pinned_at",
            "current_version_id",
            "published_build_id",
            "component_meta",
            "created_by",
            "created_at",
            "updated_at",
            "url",
        ]
        read_only_fields = fields

    def get_pinned(self, canvas: Canvas) -> bool:
        return canvas.pinned_at is not None

    def get_url(self, canvas: Canvas) -> str:
        return canvas_url(canvas)

    @extend_schema_field(CanvasComponentMetaSerializer(allow_null=True))
    def get_component_meta(self, canvas: Canvas) -> dict | None:
        if canvas.kind != Canvas.KIND_COMPONENT or canvas.current_source_version is None:
            return None
        return canvas.current_source_version.component_meta


class CanvasCreateSerializer(serializers.Serializer):
    """Payload for creating a new, empty canvas in a channel."""

    name = serializers.CharField(
        allow_blank=False,
        trim_whitespace=True,
        max_length=400,
        help_text="Display name for the canvas.",
    )
    channel_id = serializers.UUIDField(help_text="Id of the channel the canvas belongs to.")
    kind = serializers.ChoiceField(
        choices=Canvas.KINDS,
        required=False,
        default=Canvas.KIND_FREEFORM,
        help_text=(
            "What to create: 'freeform' (a standalone app), 'component' (a reusable widget for grids — "
            "its published project must declare a `component` placement contract), or 'grid' "
            "(a composition of components, edited through the layout endpoints)."
        ),
    )
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        trim_whitespace=True,
        help_text=(
            "Short prose describing the canvas. For components this is the store-search text agents "
            "match against — say what the widget shows and what its config controls."
        ),
    )
    template_id = serializers.CharField(
        required=False, default="freeform", max_length=64, help_text="Canvas template identifier."
    )

    def validate_template_id(self, value: str) -> str:
        if value in RESERVED_TEMPLATE_IDS:
            raise serializers.ValidationError("This template id is reserved for canvases PostHog seeds.")
        return value


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
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        trim_whitespace=True,
        help_text="Updated canvas description (for components, the store-search text).",
    )
    channel_id = serializers.UUIDField(required=False, help_text="Id of the space the canvas belongs to.")
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
    # Optional so projects published before the state store exist unchanged.
    state = serializers.ListField(
        child=serializers.ChoiceField(choices=CanvasState.SCOPES),
        required=False,
        default=list,
        max_length=2,
        help_text=(
            "State scopes the canvas may use via ph.state: 'user' (private to each viewer) "
            "and/or 'shared' (one value per canvas, team-visible)."
        ),
    )
    # Optional so projects published before the action registry exist unchanged.
    actions = serializers.ListField(
        child=serializers.CharField(max_length=64),
        required=False,
        default=list,
        max_length=32,
        help_text=(
            "Registered action verbs the canvas may invoke via ph.actions (e.g. 'annotations.create', "
            "'tasks.create'). Each executes as the viewer; declaring one shows it in the promote review."
        ),
    )
    agentRequests = serializers.BooleanField(required=False, default=False)


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
        help_text=("Exact-version dependencies, restricted to the platform-supported set at its pinned versions."),
    )
    canvasSdkVersion = serializers.CharField(
        required=False,
        default=canvas_sdk_version,
        help_text="Version of the host-injected `ph` canvas SDK the project targets.",
    )
    component = CanvasComponentMetaSerializer(
        required=False,
        help_text=(
            "Placement contract, required for (and only allowed on) component-kind canvases: "
            "the grid size the component takes and the JSON Schema of its per-placement config."
        ),
    )
    capabilities = CanvasCapabilitiesSerializer(
        required=False,
        default=lambda: {
            "posthog": {
                "insights": [],
                "inlineQueries": False,
                "captureEvents": [],
                "state": [],
                "actions": [],
                "agentRequests": False,
            },
            "network": {"origins": []},
        },
        help_text=(
            "Bounded capabilities frozen into the built artifact. Declare every insight short id the "
            "canvas loads, every event it captures, and inlineQueries when it runs ad-hoc HogQL — the "
            "host enforces these at runtime and validation rejects undeclared `ph` calls. Network origins must "
            "be exact HTTPS origins. Data fetched by canvas code can be sent to those origins."
        ),
    )


class CanvasGridSerializer(serializers.Serializer):
    """The grid a grid canvas lays its placements out on."""

    columns = serializers.ChoiceField(
        choices=list(GRID_COLUMN_CHOICES), help_text="Grid width in columns. One of 4, 6, 8, 10, or 12."
    )
    rowHeight = serializers.IntegerField(min_value=24, max_value=400, help_text="Height of one grid row, in pixels.")
    gap = serializers.IntegerField(min_value=0, max_value=48, help_text="Gap between placements, in pixels.")


class CanvasPlacementSerializer(serializers.Serializer):
    """One placed widget on a grid canvas."""

    id = serializers.RegexField(
        PLACEMENT_ID_RE,
        max_length=64,
        help_text="Stable placement id, unique within the layout. 1-64 characters of letters, digits, '_', or '-'.",
    )
    status = serializers.ChoiceField(
        choices=list(PLACEMENT_STATUSES),
        help_text=(
            "Placement lifecycle: 'pending' (box drawn, no prompt yet), 'generating' (an agent task is filling it), "
            "'live' (renders its component), 'failed' (generation failed; re-prompt or remove)."
        ),
    )
    component = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Id of the component canvas this placement renders. Required once the placement is live.",
    )
    version = serializers.CharField(
        required=False,
        allow_null=True,
        help_text=(
            'Component version to render: "latest" (the default — follows the component\'s published build) '
            "or a pinned source version id."
        ),
    )
    x = serializers.IntegerField(min_value=0, help_text="Left edge, in grid columns (0-based).")
    y = serializers.IntegerField(min_value=0, help_text="Top edge, in grid rows (0-based).")
    w = serializers.IntegerField(min_value=1, help_text="Width, in grid columns.")
    h = serializers.IntegerField(min_value=1, help_text="Height, in grid rows.")
    config = serializers.DictField(
        required=False,
        allow_null=True,
        help_text="Per-placement settings, validated against the component's configSchema.",
    )
    prompt = serializers.CharField(
        required=False,
        allow_null=True,
        max_length=10_000,
        trim_whitespace=False,
        help_text="For pending/generating/failed placements: what the user asked this box to become.",
    )
    generationTaskId = serializers.CharField(
        required=False,
        allow_null=True,
        help_text="Id of the agent task currently filling this placement, when one is running.",
    )


class CanvasLayoutSerializer(serializers.Serializer):
    """A grid canvas's layout document — its entire 'source'."""

    schemaVersion = serializers.ChoiceField(
        choices=[CANVAS_LAYOUT_SCHEMA_VERSION],
        help_text=f"Layout schema version. Currently always {CANVAS_LAYOUT_SCHEMA_VERSION}.",
    )
    grid = CanvasGridSerializer(help_text="The grid placements are laid out on.")
    placements = CanvasPlacementSerializer(
        many=True,
        # drf-stubs types many=True against the child serializer and misses ListSerializer's max_length
        max_length=contract_limits()["maxGridPlacements"],  # type: ignore[call-arg]
        # drf-spectacular drops a nested list serializer's max_length, so the
        # limit only reaches generated clients and MCP tools through the text.
        help_text=(
            "The placed widgets, at most "
            f"{contract_limits()['maxGridPlacements']}. Placements may not overlap or extend past the grid."
        ),
    )


class CanvasLayoutPublishSerializer(serializers.Serializer):
    """Payload for publishing a complete layout document."""

    layout = CanvasLayoutSerializer(help_text="The complete layout document to publish.")
    prompt = serializers.CharField(
        required=False,
        allow_blank=True,
        trim_whitespace=False,
        help_text="Short description of the change, stored on the appended version history entry.",
    )
    expected_current_version_id = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=False,
        help_text=(
            "Optimistic-concurrency guard: the current_version_id the layout was based on (null when the "
            "canvas has no versions yet). A moved head is rejected with 409 version_conflict. "
            "Omit to publish unguarded."
        ),
    )


class CanvasPlacementChangesSerializer(CanvasPlacementSerializer):
    """Fields to merge into an existing placement (all optional; id cannot change)."""

    id = None  # type: ignore[assignment]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.required = False


class CanvasLayoutPatchOperationSerializer(serializers.Serializer):
    """One surgical layout operation."""

    op = serializers.ChoiceField(
        choices=["set_grid", "add_placement", "update_placement", "remove_placement"],
        help_text="The operation to apply.",
    )
    grid = CanvasGridSerializer(required=False, help_text="For set_grid: the new grid definition.")
    placement = CanvasPlacementSerializer(required=False, help_text="For add_placement: the placement to add.")
    id = serializers.CharField(
        required=False, max_length=64, help_text="For update_placement/remove_placement: the target placement id."
    )
    changes = CanvasPlacementChangesSerializer(
        required=False, help_text="For update_placement: the fields to merge into the placement."
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        op = attrs["op"]
        required_by_op = {
            "set_grid": ["grid"],
            "add_placement": ["placement"],
            "update_placement": ["id", "changes"],
            "remove_placement": ["id"],
        }
        missing = [field for field in required_by_op[op] if field not in attrs]
        if missing:
            raise serializers.ValidationError(f"{op} requires: {', '.join(missing)}")
        return attrs


class CanvasLayoutPatchSerializer(serializers.Serializer):
    """Payload for applying surgical operations to the canvas's current layout."""

    operations = CanvasLayoutPatchOperationSerializer(
        many=True,
        allow_empty=False,
        # drf-stubs types many=True against the child serializer and misses ListSerializer's max_length
        max_length=MAX_LAYOUT_PATCH_OPERATIONS,  # type: ignore[call-arg]
        help_text=(
            f"Operations applied in order to the canvas's current layout, at most {MAX_LAYOUT_PATCH_OPERATIONS}."
        ),
    )
    prompt = serializers.CharField(
        required=False,
        allow_blank=True,
        trim_whitespace=False,
        help_text="Short description of the change, stored on the appended version history entry.",
    )
    expected_current_version_id = serializers.CharField(
        allow_null=True,
        help_text=(
            "Required optimistic-concurrency guard: the current_version_id the operations are based on "
            "(null when the canvas has no layout versions yet). A moved head is rejected with 409 "
            "version_conflict — patches cannot apply unguarded."
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
    kind = serializers.ChoiceField(choices=Canvas.KINDS, help_text="The canvas's kind (freeform, component, or grid).")
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
    url = serializers.SerializerMethodField(help_text=_CANVAS_URL_HELP_TEXT)

    def get_url(self, canvas: Canvas) -> str:
        return canvas_url(canvas)


class CanvasLayoutResponseSerializer(serializers.Serializer):
    """A grid canvas's layout plus the version pointer edits must be based on."""

    canvas = CanvasSummarySerializer(help_text="Identity and version pointers for the canvas.")
    layout = CanvasLayoutSerializer(
        help_text="The layout document. A grid canvas with no versions yet returns the default empty layout."
    )
    current_version_id = serializers.CharField(
        allow_null=True,
        help_text=(
            "The live layout version this document reflects — pass as expected_current_version_id when "
            "publishing or patching. Null before the first layout publish."
        ),
    )


class CanvasLayoutPublishResponseSerializer(serializers.Serializer):
    """Result of a successful layout publish or patch. The new version is live immediately — no build runs."""

    canvas = CanvasSummarySerializer(help_text="The canvas after the publish, including the new version pointer.")
    layout = CanvasLayoutSerializer(help_text="The layout document as published.")
    current_version_id = serializers.CharField(help_text="Id of the layout version this publish created.")


class CanvasVersionSerializer(serializers.Serializer):
    """One entry of a canvas's source-version history (metadata only —
    fetch a version's files via `source?version_id=`)."""

    id = serializers.UUIDField(help_text="The version's id.")
    parent_version_id = serializers.UUIDField(
        allow_null=True, help_text="The version this one was based on (null for the first publish)."
    )
    prompt = serializers.CharField(allow_null=True, help_text="Short description recorded with the publish.")
    task_id = serializers.UUIDField(allow_null=True, help_text="Task that published the version, when one did.")
    draft = serializers.BooleanField(
        help_text="True for a staged draft version that has never been the canvas head; promote it to make it live."
    )
    created_by = UserBasicSerializer(read_only=True, allow_null=True)
    created_at = serializers.DateTimeField(help_text="When the version was published.")


class CanvasDraftSerializer(serializers.Serializer):
    """A staged draft version and the status of its latest build. Preview a
    draft's files with `source?version_id=`, then make it live with `promote`."""

    version_id = serializers.CharField(help_text="Id of the draft source version.")
    prompt = serializers.CharField(allow_null=True, help_text="Short description recorded when the draft was staged.")
    created_by = UserBasicSerializer(read_only=True, allow_null=True, help_text="Who staged the draft.")
    created_at = serializers.DateTimeField(help_text="When the draft was staged.")
    build_status = serializers.ChoiceField(
        choices=["queued", "building", "ready", "failed"],
        allow_null=True,
        help_text="Status of the draft's latest build; null when no build has been recorded yet.",
    )
    build_id = serializers.CharField(allow_null=True, help_text="Id of the draft's latest build, when one exists.")


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


class CanvasPublishCurrentVersionSerializer(serializers.Serializer):
    expected_current_version_id = serializers.UUIDField(
        help_text="Current source version to publish. A changed head returns a 409 version_conflict."
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
    component = serializers.DictField(
        required=False,
        allow_null=True,
        help_text="For component artifacts: the placement contract (size, configSchema) frozen into the build.",
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


class CanvasSourceDraftSerializer(serializers.Serializer):
    """Payload for staging a complete source project as a draft build."""

    project = CanvasSourceProjectSerializer(help_text="The complete source project to stage as a draft.")
    prompt = serializers.CharField(
        required=False,
        allow_blank=True,
        trim_whitespace=False,
        help_text="Short description of the change, stored on the draft's version history entry.",
    )


class CanvasCapabilityWideningSerializer(serializers.Serializer):
    """How a draft's declared capabilities grow the current head's. A head that
    predates the capabilities snapshot reports every declaration as an addition."""

    widens = serializers.BooleanField(
        help_text="True when the draft declares any capability the current head does not."
    )
    insights_added = serializers.ListField(
        child=serializers.CharField(),
        help_text="Insight short ids the draft newly declares access to.",
    )
    capture_events_added = serializers.ListField(
        child=serializers.CharField(),
        help_text="Event names the draft newly declares it may capture.",
    )
    inline_queries_enabled = serializers.BooleanField(
        help_text="True when the draft enables inline queries and the current head does not."
    )
    agent_requests_enabled = serializers.BooleanField(
        help_text="True when the draft enables requests to the canvas's authoring agent and the current head does not."
    )
    network_origins_added = serializers.ListField(
        child=serializers.CharField(),
        help_text="Network origins the draft newly declares it may reach.",
    )
    state_scopes_added = serializers.ListField(
        child=serializers.CharField(),
        help_text="State scopes (user, shared) the draft newly declares for ph.state.",
    )
    actions_added = serializers.ListField(
        child=serializers.CharField(),
        help_text="Action verbs the draft newly declares it may invoke via ph.actions.",
    )


class CanvasActionDefinitionSerializer(serializers.Serializer):
    """One registered action verb, as the host renders it before invoking."""

    verb = serializers.CharField(help_text="The verb's registry name, e.g. 'annotations.create'.")
    summary = serializers.CharField(help_text="One line naming what invoking the verb does.")
    destructive = serializers.BooleanField(
        help_text="True when the verb deletes or disables something; the host must confirm with the viewer first."
    )
    usage = serializers.CharField(
        help_text="Authoring docs for the verb: payload and result shape, behavior, and the confirmation copy it warrants."
    )


class CanvasActionsResponseSerializer(serializers.Serializer):
    """The action registry: every verb a canvas may declare and invoke."""

    actions = CanvasActionDefinitionSerializer(many=True, help_text="Registered verbs, sorted by name.")


class CanvasActionInvokeSerializer(serializers.Serializer):
    """Payload for invoking one action verb."""

    verb = serializers.CharField(max_length=64, help_text="Registered verb to invoke, e.g. 'tasks.create'.")
    payload = serializers.DictField(
        required=False,
        default=dict,
        help_text="Verb-specific arguments, validated against the verb's payload schema.",
    )


class CanvasActionResultSerializer(serializers.Serializer):
    """Result of one action invocation."""

    verb = serializers.CharField(help_text="The verb that executed.")
    result = serializers.DictField(
        help_text="Verb-specific result, e.g. {'task_id': ...} for tasks.create.",
    )


class CanvasStateEntrySerializer(serializers.Serializer):
    """One key of a canvas's runtime key-value state (the ph.state store)."""

    scope = serializers.ChoiceField(
        choices=CanvasState.SCOPES,
        help_text="user: private to the viewer who wrote it. shared: one value per canvas, visible to every viewer.",
    )
    key = serializers.CharField(max_length=200, help_text="The entry's key, unique within its scope.")
    value = serializers.JSONField(help_text="The stored JSON value.")
    updated_at = serializers.DateTimeField(help_text="When the entry was last written.")


class CanvasStateResponseSerializer(serializers.Serializer):
    """The canvas state readable by the caller."""

    entries = CanvasStateEntrySerializer(
        many=True,
        help_text="The canvas's shared entries plus the caller's own user-scoped entries.",
    )


class CanvasStateSetSerializer(serializers.Serializer):
    """Payload for writing (or deleting) one key of a canvas's runtime state."""

    scope = serializers.ChoiceField(
        choices=CanvasState.SCOPES,
        help_text="Scope to write into; the canvas must declare it in capabilities.posthog.state.",
    )
    key = serializers.CharField(max_length=200, help_text="Key to write, unique within its scope.")
    value = serializers.JSONField(
        allow_null=True,
        help_text="JSON value to store (at most 64 KB serialized), or null to delete the key.",
    )


class CanvasSourceDraftResponseSerializer(serializers.Serializer):
    """Result of staging a draft build."""

    version_id = serializers.CharField(help_text="Id of the draft source version this request created.")
    build = CanvasBuildSerializer(help_text="The queued draft build; poll `builds` until it is terminal.")
    diagnostics = CanvasDiagnosticSerializer(
        many=True,
        help_text="Advisory (warning-severity) diagnostics recorded for the drafted project.",
    )
    capability_widening = CanvasCapabilityWideningSerializer(
        help_text="What the draft's declared capabilities grant beyond the current head's. Review before promoting."
    )


class CanvasPromoteSerializer(serializers.Serializer):
    """Payload for promoting a draft version to the canvas's live head."""

    version_id = serializers.UUIDField(help_text="Id of the draft source version to make live.")
    expected_current_version_id = serializers.UUIDField(
        allow_null=True,
        help_text=(
            "Current source version observed before requesting the promote (null when the canvas has never "
            "been published). A moved head is rejected with 409 version_conflict."
        ),
    )


class CanvasReportErrorSerializer(serializers.Serializer):
    """Payload for reporting a runtime error observed while rendering a canvas build."""

    build_id = serializers.UUIDField(help_text="Id of the build that was rendering when the error occurred.")
    error_type = serializers.CharField(
        max_length=64,
        help_text=(
            "Error class name only, for example TypeError. Values that are not a plain class-name identifier "
            "are recorded as 'unknown'. Full error messages and stack traces must stay client-side."
        ),
    )


class CanvasErrorReportResultSerializer(serializers.Serializer):
    """Outcome of filing a canvas error report."""

    report_outcome = serializers.ChoiceField(
        choices=["filed", "duplicate", "no_authoring_task", "skipped"],
        help_text=(
            "filed: a new report row was written. duplicate: this build and error type were already reported. "
            "no_authoring_task: the canvas has no linked task to notify. skipped: thread updates are unavailable."
        ),
    )


class CanvasRequestFixSerializer(serializers.Serializer):
    """Payload for asking the canvas's authoring agent to fix a failing build or runtime error."""

    build_id = serializers.UUIDField(help_text="Id of the failing or erroring build the fix should address.")
    error_type = serializers.CharField(
        required=False,
        max_length=64,
        help_text=(
            "Error class from the runtime report, when fixing a runtime error. Omit for a failed build; its "
            "diagnostics are read server-side."
        ),
    )


class CanvasFixRequestResultSerializer(serializers.Serializer):
    """Outcome of dispatching a canvas fix to the authoring agent."""

    dispatch_outcome = serializers.ChoiceField(
        choices=["signaled", "new_run", "already_queued"],
        help_text=(
            "signaled: the task's live run received the request. new_run: a fresh agent run was started. "
            "already_queued: a fix run was already starting, so no new run was created."
        ),
    )
    task_id = serializers.UUIDField(help_text="The authoring task the fix was routed to.")


class CanvasAgentRequestSerializer(serializers.Serializer):
    """A viewer-approved request for the canvas's authoring agent."""

    prompt = serializers.CharField(
        max_length=10_000,
        trim_whitespace=False,
        help_text="Exact change request the viewer reviewed and approved in the trusted host dialog.",
    )


class CanvasAgentRequestResultSerializer(serializers.Serializer):
    """Outcome of routing a canvas change request."""

    request_outcome = serializers.ChoiceField(
        choices=["signaled", "new_run", "already_queued", "reported"],
        help_text=(
            "signaled: the live run received the request. new_run: a fresh run started. "
            "already_queued: an identical run was already starting. reported: a non-creator's request was filed "
            "in the task thread for the creator."
        ),
    )
    task_id = serializers.UUIDField(help_text="Authoring task that received the request or report.")
