/**
 * Auto-generated from the Django backend OpenAPI schema.
 * To modify these types, update the Django serializers or views, then run:
 *   hogli build:openapi
 * Questions or issues? #team-devex on Slack
 *
 * PostHog API - generated
 * OpenAPI spec version: 1.0.0
 */
/**
 * * `freeform` - freeform
 * * `grid` - grid
 * * `component` - component
 */
export type CanvasKindEnumApi = (typeof CanvasKindEnumApi)[keyof typeof CanvasKindEnumApi]

export const CanvasKindEnumApi = {
    Freeform: 'freeform',
    Grid: 'grid',
    Component: 'component',
} as const

/**
 * A component's grid-size contract, in grid units.
 */
export interface CanvasComponentSizeApi {
    /**
     * Width a new placement starts at, in grid columns.
     * @minimum 1
     * @maximum 12
     */
    defaultW: number
    /**
     * Height a new placement starts at, in grid rows.
     * @minimum 1
     * @maximum 40
     */
    defaultH: number
    /**
     * Narrowest width the component renders usefully at.
     * @minimum 1
     * @maximum 12
     */
    minW: number
    /**
     * Shortest height the component renders usefully at.
     * @minimum 1
     * @maximum 40
     */
    minH: number
    /**
     * Widest allowed width; omit for no cap below the grid's width.
     * @minimum 1
     * @maximum 12
     */
    maxW?: number
    /**
     * Tallest allowed height; omit for no cap.
     * @minimum 1
     * @maximum 40
     */
    maxH?: number
}

/**
 * JSON Schema ("type": "object") for a placement's config. The host validates each placement's config against it and passes the validated object to the widget at mount.
 */
export type CanvasComponentMetaApiConfigSchema = { [key: string]: unknown }

/**
 * A component's placement contract: how grid canvases may place and configure it.
 */
export interface CanvasComponentMetaApi {
    /** Grid-size contract for placements of this component. */
    size: CanvasComponentSizeApi
    /** JSON Schema ("type": "object") for a placement's config. The host validates each placement's config against it and passes the validated object to the widget at mount. */
    configSchema?: CanvasComponentMetaApiConfigSchema
}

/**
 * * `engineering` - Engineering
 * * `data` - Data
 * * `product` - Product Management
 * * `founder` - Founder
 * * `leadership` - Leadership
 * * `marketing` - Marketing
 * * `sales` - Sales / Success
 * * `student` - Student
 * * `other` - Other
 */
export type RoleAtOrganizationEnumApi = (typeof RoleAtOrganizationEnumApi)[keyof typeof RoleAtOrganizationEnumApi]

export const RoleAtOrganizationEnumApi = {
    Engineering: 'engineering',
    Data: 'data',
    Product: 'product',
    Founder: 'founder',
    Leadership: 'leadership',
    Marketing: 'marketing',
    Sales: 'sales',
    Student: 'student',
    Other: 'other',
} as const

export type BlankEnumApi = (typeof BlankEnumApi)[keyof typeof BlankEnumApi]

export const BlankEnumApi = {
    '': '',
} as const

/**
 * @nullable
 */
export type UserBasicApiHedgehogConfig = { [key: string]: unknown } | null

export interface UserBasicApi {
    readonly id: number
    readonly uuid: string
    /**
     * @maxLength 200
     * @nullable
     */
    distinct_id?: string | null
    /** @maxLength 150 */
    first_name?: string
    /** @maxLength 150 */
    last_name?: string
    /** @maxLength 254 */
    email: string
    /** @nullable */
    is_email_verified?: boolean | null
    /** @nullable */
    readonly hedgehog_config: UserBasicApiHedgehogConfig
    role_at_organization?: RoleAtOrganizationEnumApi | BlankEnumApi | null
}

/**
 * A canvas document. Version/build content hangs off the source and build endpoints.
 */
export interface CanvasApi {
    readonly id: string
    readonly name: string
    /** What the canvas is: 'freeform' (a standalone app), 'component' (a reusable widget grids place), or 'grid' (a composition of components).
     *
     * * `freeform` - freeform
     * * `grid` - grid
     * * `component` - component */
    readonly kind: CanvasKindEnumApi
    /** Short prose describing the canvas. For components, the store-search text. */
    readonly description: string
    readonly channel: string
    readonly template_id: string
    readonly context: string
    /** @nullable */
    readonly generation_task_id: string | null
    /** Whether the canvas is pinned to its channel. */
    readonly pinned: boolean
    /** @nullable */
    readonly pinned_at: string | null
    /**
     * Id of the live source version — pass as expected_current_version_id on publish. Null before the first publish.
     * @nullable
     */
    readonly current_version_id: string | null
    /**
     * Id of the canvas's live (last successful, still-eligible) build. Null until a build completes.
     * @nullable
     */
    readonly published_build_id: string | null
    /** For component-kind canvases: the head version's placement contract (size, optional configSchema). Null for other kinds and unpublished components. */
    readonly component_meta: CanvasComponentMetaApi | null
    readonly created_by: UserBasicApi
    readonly created_at: string
    readonly updated_at: string
    /** Canonical link to the canvas in the PostHog app. The only valid way to link to a canvas — share this when pointing a user at it; never construct a canvas URL. */
    readonly url: string
}

export interface PaginatedCanvasListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: CanvasApi[]
}

/**
 * Payload for creating a new, empty canvas in a channel.
 */
export interface CanvasCreateApi {
    /**
     * Display name for the canvas.
     * @maxLength 400
     */
    name: string
    /** Id of the channel the canvas belongs to. */
    channel_id: string
    /** What to create: 'freeform' (a standalone app), 'component' (a reusable widget for grids — its published project must declare a `component` placement contract), or 'grid' (a composition of components, edited through the layout endpoints).
     *
     * * `freeform` - freeform
     * * `grid` - grid
     * * `component` - component */
    kind?: CanvasKindEnumApi
    /** Short prose describing the canvas. For components this is the store-search text agents match against — say what the widget shows and what its config controls. */
    description?: string
    /**
     * Canvas template identifier.
     * @maxLength 64
     */
    template_id?: string
}

/**
 * Writable canvas fields: metadata only — source changes go through publish/edit.
 */
export interface PatchedCanvasUpdateApi {
    /**
     * Updated display name.
     * @maxLength 400
     */
    name?: string
    /** Updated author context markdown. */
    context?: string
    /** Updated canvas description (for components, the store-search text). */
    description?: string
    /** Id of the space the canvas belongs to. */
    channel_id?: string
    /** Whether the canvas is pinned in its channel. */
    pinned?: boolean
    /**
     * Task currently generating this canvas, or null to clear it.
     * @nullable
     */
    generation_task_id?: string | null
}

/**
 * Verb-specific arguments, validated against the verb's payload schema.
 */
export type CanvasActionInvokeApiPayload = { [key: string]: unknown }

/**
 * Payload for invoking one action verb.
 */
export interface CanvasActionInvokeApi {
    /**
     * Registered verb to invoke, e.g. 'tasks.create'.
     * @maxLength 64
     */
    verb: string
    /** Verb-specific arguments, validated against the verb's payload schema. */
    payload?: CanvasActionInvokeApiPayload
}

/**
 * Verb-specific result, e.g. {'task_id': ...} for tasks.create.
 */
export type CanvasActionResultApiResult = { [key: string]: unknown }

/**
 * Result of one action invocation.
 */
export interface CanvasActionResultApi {
    /** The verb that executed. */
    verb: string
    /** Verb-specific result, e.g. {'task_id': ...} for tasks.create. */
    result: CanvasActionResultApiResult
}

/**
 * * `queued` - queued
 * * `building` - building
 * * `ready` - ready
 * * `failed` - failed
 */
export type BuildStatusEnumApi = (typeof BuildStatusEnumApi)[keyof typeof BuildStatusEnumApi]

export const BuildStatusEnumApi = {
    Queued: 'queued',
    Building: 'building',
    Ready: 'ready',
    Failed: 'failed',
} as const

/**
 * * `error` - error
 * * `warning` - warning
 */
export type DiagnosticSeverityEnumApi = (typeof DiagnosticSeverityEnumApi)[keyof typeof DiagnosticSeverityEnumApi]

export const DiagnosticSeverityEnumApi = {
    Error: 'error',
    Warning: 'warning',
} as const

/**
 * One structured validation/build diagnostic for a canvas source project.
 */
export interface CanvasDiagnosticApi {
    /** 'error' blocks publishing; 'warning' is advisory and does not block.
     *
     * * `error` - error
     * * `warning` - warning */
    severity: DiagnosticSeverityEnumApi
    /** Stable machine-readable diagnostic code, e.g. 'import_not_allowed' or 'capability_missing_insight'. */
    code: string
    /** Human-readable description of the problem and how to fix it. */
    message: string
    /** Project-relative path of the file the diagnostic points at, when file-specific. */
    path?: string
    /** 1-based line number within `path`, when the diagnostic points at a specific line. */
    line?: number
}

/**
 * One emitted file of a built canvas artifact.
 */
export interface CanvasArtifactAssetApi {
    /** Artifact-relative path of the emitted file. */
    path: string
    /** Hex SHA-256 of the file content. */
    contentHash: string
    /** Size of the file in bytes. */
    sizeBytes: number
}

/**
 * Exact dependency versions the artifact was built against.
 */
export type CanvasArtifactManifestApiDependencies = { [key: string]: string }

/**
 * Declared PostHog/network capabilities the artifact is held to at runtime.
 */
export type CanvasArtifactManifestApiCapabilities = { [key: string]: unknown }

/**
 * For component artifacts: the placement contract (size, configSchema) frozen into the build.
 * @nullable
 */
export type CanvasArtifactManifestApiComponent = { [key: string]: unknown } | null

/**
 * The manifest frozen into a ready build: entry, assets, versions, capabilities.
 */
export interface CanvasArtifactManifestApi {
    /** The artifact's entry HTML file. */
    entryHtml: string
    /** Every emitted artifact file with its content hash. */
    assets: CanvasArtifactAssetApi[]
    /** Exact dependency versions the artifact was built against. */
    dependencies: CanvasArtifactManifestApiDependencies
    /** Version of the `ph` canvas SDK the artifact targets. */
    canvasSdkVersion: string
    /**
     * Path of the runtime-mounted React component, for legacy-tier artifacts.
     * @nullable
     */
    legacyComponentPath?: string | null
    /**
     * The runtime-mounted component source, for legacy-tier artifacts.
     * @nullable
     */
    legacyCode?: string | null
    /** Declared PostHog/network capabilities the artifact is held to at runtime. */
    capabilities: CanvasArtifactManifestApiCapabilities
    /**
     * For component artifacts: the placement contract (size, configSchema) frozen into the build.
     * @nullable
     */
    component?: CanvasArtifactManifestApiComponent
}

/**
 * Lifecycle record of one build of a canvas source version.
 */
export interface CanvasBuildApi {
    /** The build's id. */
    id: string
    /** The source version this build compiled. */
    source_version_id: string
    /** Build lifecycle state. A failed build never replaces the last-known-good artifact.
     *
     * * `queued` - queued
     * * `building` - building
     * * `ready` - ready
     * * `failed` - failed */
    build_status: BuildStatusEnumApi
    /** Structured diagnostics recorded by the build (errors explain a failed status). */
    diagnostics: CanvasDiagnosticApi[]
    /** The frozen artifact manifest — present once the build is ready. */
    manifest?: CanvasArtifactManifestApi | null
    /**
     * Hex SHA-256 over the manifest — the artifact's integrity anchor. Null until ready.
     * @nullable
     */
    integrity: string | null
    /**
     * Signed URL for the ready build's entry HTML. Null until ready or when artifact delivery is unavailable.
     * @nullable
     */
    readonly artifact_url: string | null
    /** Pinned builds are retained for the lifetime of the canvas. */
    pinned: boolean
    /** When the build was queued. */
    created_at: string
    /**
     * When the build reached a terminal state.
     * @nullable
     */
    finished_at: string | null
}

/**
 * A canvas's build lifecycle: live pointers plus its most recent builds.
 */
export interface CanvasBuildsResponseApi {
    /**
     * Id of the canvas's live build (the last successful, still-eligible one). Null until a build completes.
     * @nullable
     */
    published_build_id: string | null
    /**
     * Id of the source version the canvas's head points at.
     * @nullable
     */
    current_version_id: string | null
    /** Most recent builds, newest first (capped at 20; the live build is always included). */
    builds: CanvasBuildApi[]
}

/**
 * * `retry` - retry
 * * `pin` - pin
 * * `unpin` - unpin
 * * `cancel` - cancel
 */
export type CanvasBuildActionActionEnumApi =
    (typeof CanvasBuildActionActionEnumApi)[keyof typeof CanvasBuildActionActionEnumApi]

export const CanvasBuildActionActionEnumApi = {
    Retry: 'retry',
    Pin: 'pin',
    Unpin: 'unpin',
    Cancel: 'cancel',
} as const

export interface CanvasBuildActionApi {
    action: CanvasBuildActionActionEnumApi
    build_id: string
}

/**
 * * `base64` - base64
 */
export type EncodingEnumApi = (typeof EncodingEnumApi)[keyof typeof EncodingEnumApi]

export const EncodingEnumApi = {
    Base64: 'base64',
} as const

/**
 * * `image/png` - image/png
 * * `image/jpeg` - image/jpeg
 * * `image/gif` - image/gif
 * * `image/webp` - image/webp
 * * `image/svg+xml` - image/svg+xml
 * * `font/woff` - font/woff
 * * `font/woff2` - font/woff2
 * * `application/wasm` - application/wasm
 * * `application/octet-stream` - application/octet-stream
 */
export type ContentTypeEnumApi = (typeof ContentTypeEnumApi)[keyof typeof ContentTypeEnumApi]

export const ContentTypeEnumApi = {
    ImagePng: 'image/png',
    ImageJpeg: 'image/jpeg',
    ImageGif: 'image/gif',
    ImageWebp: 'image/webp',
    ImageSvgXml: 'image/svg+xml',
    FontWoff: 'font/woff',
    FontWoff2: 'font/woff2',
    ApplicationWasm: 'application/wasm',
    ApplicationOctetStream: 'application/octet-stream',
} as const

export interface CanvasSourceAssetApi {
    encoding: EncodingEnumApi
    contentType: ContentTypeEnumApi
    /**
     * @maxLength 2796204
     * @pattern ^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$
     */
    content: string
}

/**
 * * `user` - user
 * * `shared` - shared
 */
export type CanvasStateScopeEnumApi = (typeof CanvasStateScopeEnumApi)[keyof typeof CanvasStateScopeEnumApi]

export const CanvasStateScopeEnumApi = {
    User: 'user',
    Shared: 'shared',
} as const

export interface CanvasPostHogCapabilitiesApi {
    /**
     * @maxItems 100
     * @items.maxLength 128
     */
    insights: string[]
    inlineQueries: boolean
    /**
     * @maxItems 100
     * @items.maxLength 200
     */
    captureEvents: string[]
    /**
     * State scopes the canvas may use via ph.state: 'user' (private to each viewer) and/or 'shared' (one value per canvas, team-visible).
     * @maxItems 2
     */
    state?: CanvasStateScopeEnumApi[]
    /**
     * Registered action verbs the canvas may invoke via ph.actions (e.g. 'annotations.create', 'tasks.create'). Each executes as the viewer; declaring one shows it in the promote review.
     * @maxItems 32
     * @items.maxLength 64
     */
    actions?: string[]
    agentRequests?: boolean
}

export interface CanvasNetworkCapabilitiesApi {
    /**
     * @maxItems 20
     * @items.maxLength 2048
     */
    origins: string[]
}

export interface CanvasCapabilitiesApi {
    posthog: CanvasPostHogCapabilitiesApi
    network: CanvasNetworkCapabilitiesApi
}

/**
 * Project files keyed by relative path (forward slashes, no '..').
 */
export type CanvasSourceProjectApiFiles = { [key: string]: string }

/**
 * Optional base64-encoded binary assets keyed by safe project-relative paths.
 */
export type CanvasSourceProjectApiAssets = { [key: string]: CanvasSourceAssetApi }

/**
 * Exact-version dependencies, restricted to the platform-supported set at its pinned versions.
 */
export type CanvasSourceProjectApiDependencies = { [key: string]: string }

/**
 * A canvas's multi-file source project — the canonical write format for canvas source.
 */
export interface CanvasSourceProjectApi {
    /** Source-project schema version. Currently always 1. */
    schemaVersion: number
    /** Project files keyed by relative path (forward slashes, no '..'). */
    files: CanvasSourceProjectApiFiles
    /** Optional base64-encoded binary assets keyed by safe project-relative paths. */
    assets?: CanvasSourceProjectApiAssets
    /** The project's entry HTML file. Currently always "index.html". */
    entryHtml: string
    /** Exact-version dependencies, restricted to the platform-supported set at its pinned versions. */
    dependencies?: CanvasSourceProjectApiDependencies
    /** Version of the host-injected `ph` canvas SDK the project targets. */
    canvasSdkVersion?: string
    /** Placement contract, required for (and only allowed on) component-kind canvases: the grid size the component takes and the JSON Schema of its per-placement config. */
    component?: CanvasComponentMetaApi
    /** Bounded capabilities frozen into the built artifact. Declare every insight short id the canvas loads, every event it captures, and inlineQueries when it runs ad-hoc HogQL — the host enforces these at runtime and validation rejects undeclared `ph` calls. Network origins must be exact HTTPS origins. Data fetched by canvas code can be sent to those origins. */
    capabilities?: CanvasCapabilitiesApi
}

/**
 * Payload for staging a complete source project as a draft build.
 */
export interface CanvasSourceDraftApi {
    /** The complete source project to stage as a draft. */
    project: CanvasSourceProjectApi
    /** Short description of the change, stored on the draft's version history entry. */
    prompt?: string
}

/**
 * How a draft's declared capabilities grow the current head's. A head that
 * predates the capabilities snapshot reports every declaration as an addition.
 */
export interface CanvasCapabilityWideningApi {
    /** True when the draft declares any capability the current head does not. */
    widens: boolean
    /** Insight short ids the draft newly declares access to. */
    insights_added: string[]
    /** Event names the draft newly declares it may capture. */
    capture_events_added: string[]
    /** True when the draft enables inline queries and the current head does not. */
    inline_queries_enabled: boolean
    /** True when the draft enables requests to the canvas's authoring agent and the current head does not. */
    agent_requests_enabled: boolean
    /** Network origins the draft newly declares it may reach. */
    network_origins_added: string[]
    /** State scopes (user, shared) the draft newly declares for ph.state. */
    state_scopes_added: string[]
    /** Action verbs the draft newly declares it may invoke via ph.actions. */
    actions_added: string[]
}

/**
 * Result of staging a draft build.
 */
export interface CanvasSourceDraftResponseApi {
    /** Id of the draft source version this request created. */
    version_id: string
    /** The queued draft build; poll `builds` until it is terminal. */
    build: CanvasBuildApi
    /** Advisory (warning-severity) diagnostics recorded for the drafted project. */
    diagnostics: CanvasDiagnosticApi[]
    /** What the draft's declared capabilities grant beyond the current head's. Review before promoting. */
    capability_widening: CanvasCapabilityWideningApi
}

/**
 * 400 body for a publish whose source project failed validation.
 */
export interface CanvasSourceInvalidApi {
    /** Human-readable summary of why the project was rejected. */
    detail: string
    /** Always "invalid_source_project". */
    code: string
    /** The validation diagnostics, including at least one error. */
    diagnostics: CanvasDiagnosticApi[]
}

/**
 * A staged draft version and the status of its latest build. Preview a
 * draft's files with `source?version_id=`, then make it live with `promote`.
 */
export interface CanvasDraftApi {
    /** Id of the draft source version. */
    version_id: string
    /**
     * Short description recorded when the draft was staged.
     * @nullable
     */
    prompt: string | null
    /** Who staged the draft. */
    readonly created_by: UserBasicApi | null
    /** When the draft was staged. */
    created_at: string
    /** Status of the draft's latest build; null when no build has been recorded yet.
     *
     * * `queued` - queued
     * * `building` - building
     * * `ready` - ready
     * * `failed` - failed */
    build_status: BuildStatusEnumApi | null
    /**
     * Id of the draft's latest build, when one exists.
     * @nullable
     */
    build_id: string | null
}

export interface PaginatedCanvasDraftListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: CanvasDraftApi[]
}

/**
 * One per-file edit: set a file's content, or delete it.
 */
export interface CanvasSourceEditOperationApi {
    /** Project-relative path of the file to write or delete (e.g. "src/canvas.tsx"). */
    path: string
    /**
     * The file's complete new content. Null (or omitted) deletes the file.
     * @nullable
     */
    content?: string | null
}

/**
 * Payload for publishing per-file edits against the canvas's current source.
 */
export interface CanvasSourceEditApi {
    /** Edits applied in order to the canvas's current source project. */
    operations: CanvasSourceEditOperationApi[]
    /** Short description of the change, stored on the appended version history entry. */
    prompt?: string
    /**
     * Optional new display name for the canvas.
     * @maxLength 400
     */
    name?: string
    /**
     * Required optimistic-concurrency guard: the current_version_id the edits are based on (null when the canvas has never been published). Diff edits against a moved head are rejected with 409 version_conflict — they cannot be published unguarded.
     * @nullable
     */
    expected_current_version_id: string | null
}

/**
 * Identity and version pointers for one canvas.
 */
export interface CanvasSummaryApi {
    /** The canvas's id. */
    id: string
    /** Display name of the canvas. */
    name: string
    /** The canvas's kind (freeform, component, or grid).
     *
     * * `freeform` - freeform
     * * `grid` - grid
     * * `component` - component */
    kind: CanvasKindEnumApi
    /** Id of the channel the canvas belongs to. */
    channel_id: string
    /**
     * Id of the live source version — pass as expected_current_version_id on publish. Null before the first publish.
     * @nullable
     */
    current_version_id: string | null
    /**
     * Id of the canvas's live (last successful, still-eligible) build. Null until a build completes.
     * @nullable
     */
    published_build_id: string | null
    /** When the canvas was created. */
    created_at: string
    /** Canonical link to the canvas in the PostHog app. The only valid way to link to a canvas — share this when pointing a user at it; never construct a canvas URL. */
    readonly url: string
}

/**
 * Result of a successful source-project publish.
 */
export interface CanvasSourcePublishResponseApi {
    /** The canvas after the publish, including the new version pointer. */
    canvas: CanvasSummaryApi
    /** Id of the source version this publish created. */
    current_version_id: string
    /** Advisory (warning-severity) diagnostics recorded for the published project. */
    diagnostics: CanvasDiagnosticApi[]
}

/**
 * 409 body for a guarded canvas publish based on a stale version.
 */
export interface CanvasPublishConflictApi {
    /** Human-readable description of the conflict and how to recover. */
    detail: string
    /** Always "version_conflict". */
    code: string
    /**
     * The canvas's live current_version_id at rejection time (null when the canvas has no versions).
     * @nullable
     */
    current_version_id: string | null
}

/**
 * * `1` - 1
 */
export type CanvasLayoutSchemaVersionEnumApi =
    (typeof CanvasLayoutSchemaVersionEnumApi)[keyof typeof CanvasLayoutSchemaVersionEnumApi]

export const CanvasLayoutSchemaVersionEnumApi = {
    Number1: 1,
} as const

/**
 * * `4` - 4
 * * `6` - 6
 * * `8` - 8
 * * `10` - 10
 * * `12` - 12
 */
export type CanvasGridColumnsEnumApi = (typeof CanvasGridColumnsEnumApi)[keyof typeof CanvasGridColumnsEnumApi]

export const CanvasGridColumnsEnumApi = {
    Number4: 4,
    Number6: 6,
    Number8: 8,
    Number10: 10,
    Number12: 12,
} as const

/**
 * The grid a grid canvas lays its placements out on.
 */
export interface CanvasGridApi {
    /** Grid width in columns. One of 4, 6, 8, 10, or 12.
     *
     * * `4` - 4
     * * `6` - 6
     * * `8` - 8
     * * `10` - 10
     * * `12` - 12 */
    columns: CanvasGridColumnsEnumApi
    /**
     * Height of one grid row, in pixels.
     * @minimum 24
     * @maximum 400
     */
    rowHeight: number
    /**
     * Gap between placements, in pixels.
     * @minimum 0
     * @maximum 48
     */
    gap: number
}

/**
 * * `pending` - pending
 * * `generating` - generating
 * * `live` - live
 * * `failed` - failed
 */
export type CanvasPlacementStatusEnumApi =
    (typeof CanvasPlacementStatusEnumApi)[keyof typeof CanvasPlacementStatusEnumApi]

export const CanvasPlacementStatusEnumApi = {
    Pending: 'pending',
    Generating: 'generating',
    Live: 'live',
    Failed: 'failed',
} as const

/**
 * Per-placement settings, validated against the component's configSchema.
 * @nullable
 */
export type CanvasPlacementApiConfig = { [key: string]: unknown } | null

/**
 * One placed widget on a grid canvas.
 */
export interface CanvasPlacementApi {
    /**
     * Stable placement id, unique within the layout. 1-64 characters of letters, digits, '_', or '-'.
     * @maxLength 64
     * @pattern ^[A-Za-z0-9_-]{1,64}$
     */
    id: string
    /** Placement lifecycle: 'pending' (box drawn, no prompt yet), 'generating' (an agent task is filling it), 'live' (renders its component), 'failed' (generation failed; re-prompt or remove).
     *
     * * `pending` - pending
     * * `generating` - generating
     * * `live` - live
     * * `failed` - failed */
    status: CanvasPlacementStatusEnumApi
    /**
     * Id of the component canvas this placement renders. Required once the placement is live.
     * @nullable
     */
    component?: string | null
    /**
     * Component version to render: "latest" (the default — follows the component's published build) or a pinned source version id.
     * @nullable
     */
    version?: string | null
    /**
     * Left edge, in grid columns (0-based).
     * @minimum 0
     */
    x: number
    /**
     * Top edge, in grid rows (0-based).
     * @minimum 0
     */
    y: number
    /**
     * Width, in grid columns.
     * @minimum 1
     */
    w: number
    /**
     * Height, in grid rows.
     * @minimum 1
     */
    h: number
    /**
     * Per-placement settings, validated against the component's configSchema.
     * @nullable
     */
    config?: CanvasPlacementApiConfig
    /**
     * For pending/generating/failed placements: what the user asked this box to become.
     * @maxLength 10000
     * @nullable
     */
    prompt?: string | null
    /**
     * Id of the agent task currently filling this placement, when one is running.
     * @nullable
     */
    generationTaskId?: string | null
}

/**
 * A grid canvas's layout document — its entire 'source'.
 */
export interface CanvasLayoutApi {
    /** Layout schema version. Currently always 1.
     *
     * * `1` - 1 */
    schemaVersion: CanvasLayoutSchemaVersionEnumApi
    /** The grid placements are laid out on. */
    grid: CanvasGridApi
    /** The placed widgets, at most 24. Placements may not overlap or extend past the grid. */
    placements: CanvasPlacementApi[]
}

/**
 * A grid canvas's layout plus the version pointer edits must be based on.
 */
export interface CanvasLayoutResponseApi {
    /** Identity and version pointers for the canvas. */
    canvas: CanvasSummaryApi
    /** The layout document. A grid canvas with no versions yet returns the default empty layout. */
    layout: CanvasLayoutApi
    /**
     * The live layout version this document reflects — pass as expected_current_version_id when publishing or patching. Null before the first layout publish.
     * @nullable
     */
    current_version_id: string | null
}

/**
 * * `set_grid` - set_grid
 * * `add_placement` - add_placement
 * * `update_placement` - update_placement
 * * `remove_placement` - remove_placement
 */
export type CanvasLayoutOpEnumApi = (typeof CanvasLayoutOpEnumApi)[keyof typeof CanvasLayoutOpEnumApi]

export const CanvasLayoutOpEnumApi = {
    SetGrid: 'set_grid',
    AddPlacement: 'add_placement',
    UpdatePlacement: 'update_placement',
    RemovePlacement: 'remove_placement',
} as const

/**
 * Per-placement settings, validated against the component's configSchema.
 * @nullable
 */
export type CanvasPlacementChangesApiConfig = { [key: string]: unknown } | null

/**
 * Fields to merge into an existing placement (all optional; id cannot change).
 */
export interface CanvasPlacementChangesApi {
    /** Placement lifecycle: 'pending' (box drawn, no prompt yet), 'generating' (an agent task is filling it), 'live' (renders its component), 'failed' (generation failed; re-prompt or remove).
     *
     * * `pending` - pending
     * * `generating` - generating
     * * `live` - live
     * * `failed` - failed */
    status?: CanvasPlacementStatusEnumApi
    /**
     * Id of the component canvas this placement renders. Required once the placement is live.
     * @nullable
     */
    component?: string | null
    /**
     * Component version to render: "latest" (the default — follows the component's published build) or a pinned source version id.
     * @nullable
     */
    version?: string | null
    /**
     * Left edge, in grid columns (0-based).
     * @minimum 0
     */
    x?: number
    /**
     * Top edge, in grid rows (0-based).
     * @minimum 0
     */
    y?: number
    /**
     * Width, in grid columns.
     * @minimum 1
     */
    w?: number
    /**
     * Height, in grid rows.
     * @minimum 1
     */
    h?: number
    /**
     * Per-placement settings, validated against the component's configSchema.
     * @nullable
     */
    config?: CanvasPlacementChangesApiConfig
    /**
     * For pending/generating/failed placements: what the user asked this box to become.
     * @maxLength 10000
     * @nullable
     */
    prompt?: string | null
    /**
     * Id of the agent task currently filling this placement, when one is running.
     * @nullable
     */
    generationTaskId?: string | null
}

/**
 * One surgical layout operation.
 */
export interface CanvasLayoutPatchOperationApi {
    /** The operation to apply.
     *
     * * `set_grid` - set_grid
     * * `add_placement` - add_placement
     * * `update_placement` - update_placement
     * * `remove_placement` - remove_placement */
    op: CanvasLayoutOpEnumApi
    /** For set_grid: the new grid definition. */
    grid?: CanvasGridApi
    /** For add_placement: the placement to add. */
    placement?: CanvasPlacementApi
    /**
     * For update_placement/remove_placement: the target placement id.
     * @maxLength 64
     */
    id?: string
    /** For update_placement: the fields to merge into the placement. */
    changes?: CanvasPlacementChangesApi
}

/**
 * Payload for applying surgical operations to the canvas's current layout.
 */
export interface CanvasLayoutPatchApi {
    /** Operations applied in order to the canvas's current layout, at most 64. */
    operations: CanvasLayoutPatchOperationApi[]
    /** Short description of the change, stored on the appended version history entry. */
    prompt?: string
    /**
     * Required optimistic-concurrency guard: the current_version_id the operations are based on (null when the canvas has no layout versions yet). A moved head is rejected with 409 version_conflict — patches cannot apply unguarded.
     * @nullable
     */
    expected_current_version_id: string | null
}

/**
 * Result of a successful layout publish or patch. The new version is live immediately — no build runs.
 */
export interface CanvasLayoutPublishResponseApi {
    /** The canvas after the publish, including the new version pointer. */
    canvas: CanvasSummaryApi
    /** The layout document as published. */
    layout: CanvasLayoutApi
    /** Id of the layout version this publish created. */
    current_version_id: string
}

/**
 * Payload for publishing a complete layout document.
 */
export interface CanvasLayoutPublishApi {
    /** The complete layout document to publish. */
    layout: CanvasLayoutApi
    /** Short description of the change, stored on the appended version history entry. */
    prompt?: string
    /**
     * Optimistic-concurrency guard: the current_version_id the layout was based on (null when the canvas has no versions yet). A moved head is rejected with 409 version_conflict. Omit to publish unguarded.
     * @nullable
     */
    expected_current_version_id?: string | null
}

/**
 * Payload for promoting a draft version to the canvas's live head.
 */
export interface CanvasPromoteApi {
    /** Id of the draft source version to make live. */
    version_id: string
    /**
     * Current source version observed before requesting the promote (null when the canvas has never been published). A moved head is rejected with 409 version_conflict.
     * @nullable
     */
    expected_current_version_id: string | null
}

/**
 * Payload for publishing a complete canvas source project.
 */
export interface CanvasSourcePublishApi {
    /** The complete source project to publish. */
    project: CanvasSourceProjectApi
    /** Short description of the change, stored on the appended version history entry. */
    prompt?: string
    /**
     * Optional new display name for the canvas.
     * @maxLength 400
     */
    name?: string
    /**
     * Optimistic-concurrency guard: the current_version_id the publisher based its edits on (null when it read a canvas with no versions yet). When the canvas has since moved past it the publish is rejected with a 409 version_conflict instead of overwriting the newer head. Omit to publish unguarded.
     * @nullable
     */
    expected_current_version_id?: string | null
}

export interface CanvasPublishCurrentVersionApi {
    /** Current source version to publish. A changed head returns a 409 version_conflict. */
    expected_current_version_id: string
}

/**
 * Payload for reporting a runtime error observed while rendering a canvas build.
 */
export interface CanvasReportErrorApi {
    /** Id of the build that was rendering when the error occurred. */
    build_id: string
    /**
     * Error class name only, for example TypeError. Values that are not a plain class-name identifier are recorded as 'unknown'. Full error messages and stack traces must stay client-side.
     * @maxLength 64
     */
    error_type: string
}

/**
 * * `filed` - filed
 * * `duplicate` - duplicate
 * * `no_authoring_task` - no_authoring_task
 * * `skipped` - skipped
 */
export type ReportOutcomeEnumApi = (typeof ReportOutcomeEnumApi)[keyof typeof ReportOutcomeEnumApi]

export const ReportOutcomeEnumApi = {
    Filed: 'filed',
    Duplicate: 'duplicate',
    NoAuthoringTask: 'no_authoring_task',
    Skipped: 'skipped',
} as const

/**
 * Outcome of filing a canvas error report.
 */
export interface CanvasErrorReportResultApi {
    /** filed: a new report row was written. duplicate: this build and error type were already reported. no_authoring_task: the canvas has no linked task to notify. skipped: thread updates are unavailable.
     *
     * * `filed` - filed
     * * `duplicate` - duplicate
     * * `no_authoring_task` - no_authoring_task
     * * `skipped` - skipped */
    report_outcome: ReportOutcomeEnumApi
}

/**
 * A viewer-approved request for the canvas's authoring agent.
 */
export interface CanvasAgentRequestApi {
    /**
     * Exact change request the viewer reviewed and approved in the trusted host dialog.
     * @maxLength 10000
     */
    prompt: string
}

/**
 * * `signaled` - signaled
 * * `new_run` - new_run
 * * `already_queued` - already_queued
 * * `reported` - reported
 */
export type RequestOutcomeEnumApi = (typeof RequestOutcomeEnumApi)[keyof typeof RequestOutcomeEnumApi]

export const RequestOutcomeEnumApi = {
    Signaled: 'signaled',
    NewRun: 'new_run',
    AlreadyQueued: 'already_queued',
    Reported: 'reported',
} as const

/**
 * Outcome of routing a canvas change request.
 */
export interface CanvasAgentRequestResultApi {
    /** signaled: the live run received the request. new_run: a fresh run started. already_queued: an identical run was already starting. reported: a non-creator's request was filed in the task thread for the creator.
     *
     * * `signaled` - signaled
     * * `new_run` - new_run
     * * `already_queued` - already_queued
     * * `reported` - reported */
    request_outcome: RequestOutcomeEnumApi
    /** Authoring task that received the request or report. */
    task_id: string
}

/**
 * Payload for asking the canvas's authoring agent to fix a failing build or runtime error.
 */
export interface CanvasRequestFixApi {
    /** Id of the failing or erroring build the fix should address. */
    build_id: string
    /**
     * Error class from the runtime report, when fixing a runtime error. Omit for a failed build; its diagnostics are read server-side.
     * @maxLength 64
     */
    error_type?: string
}

/**
 * * `signaled` - signaled
 * * `new_run` - new_run
 * * `already_queued` - already_queued
 */
export type DispatchOutcomeEnumApi = (typeof DispatchOutcomeEnumApi)[keyof typeof DispatchOutcomeEnumApi]

export const DispatchOutcomeEnumApi = {
    Signaled: 'signaled',
    NewRun: 'new_run',
    AlreadyQueued: 'already_queued',
} as const

/**
 * Outcome of dispatching a canvas fix to the authoring agent.
 */
export interface CanvasFixRequestResultApi {
    /** signaled: the task's live run received the request. new_run: a fresh agent run was started. already_queued: a fix run was already starting, so no new run was created.
     *
     * * `signaled` - signaled
     * * `new_run` - new_run
     * * `already_queued` - already_queued */
    dispatch_outcome: DispatchOutcomeEnumApi
    /** The authoring task the fix was routed to. */
    task_id: string
}

/**
 * Payload for reverting the canvas's head to an existing source version.
 */
export interface CanvasRevertApi {
    /** Id of the source version to make the head again. */
    version_id: string
    /**
     * Current source version observed before requesting the revert.
     * @nullable
     */
    expected_current_version_id: string | null
}

/**
 * A canvas's source project plus the version pointer edits must be based on.
 */
export interface CanvasSourceResponseApi {
    /** Identity and version pointers for the canvas. */
    canvas: CanvasSummaryApi
    /** The canvas's source project. Pre-relational single-file canvases are presented as a synthetic project. */
    project: CanvasSourceProjectApi
    /**
     * The live source version this project reflects — pass as expected_current_version_id when publishing an edit. Null before the first publish.
     * @nullable
     */
    current_version_id: string | null
}

/**
 * One key of a canvas's runtime key-value state (the ph.state store).
 */
export interface CanvasStateEntryApi {
    /** user: private to the viewer who wrote it. shared: one value per canvas, visible to every viewer.
     *
     * * `user` - user
     * * `shared` - shared */
    scope: CanvasStateScopeEnumApi
    /**
     * The entry's key, unique within its scope.
     * @maxLength 200
     */
    key: string
    /** The stored JSON value. */
    value: unknown
    /** When the entry was last written. */
    updated_at: string
}

/**
 * The canvas state readable by the caller.
 */
export interface CanvasStateResponseApi {
    /** The canvas's shared entries plus the caller's own user-scoped entries. */
    entries: CanvasStateEntryApi[]
}

/**
 * Payload for writing (or deleting) one key of a canvas's runtime state.
 */
export interface CanvasStateSetApi {
    /** Scope to write into; the canvas must declare it in capabilities.posthog.state.
     *
     * * `user` - user
     * * `shared` - shared */
    scope: CanvasStateScopeEnumApi
    /**
     * Key to write, unique within its scope.
     * @maxLength 200
     */
    key: string
    /** JSON value to store (at most 64 KB serialized), or null to delete the key. */
    value: unknown
}

/**
 * Payload for validating a candidate source project without publishing it.
 */
export interface CanvasValidateRequestApi {
    /** The candidate source project to validate. */
    project: CanvasSourceProjectApi
}

/**
 * Validation outcome for a candidate source project.
 */
export interface CanvasValidateResponseApi {
    /** True when the project has no error-severity diagnostics. */
    valid: boolean
    /** Structured diagnostics; errors block publishing, warnings are advisory. */
    diagnostics: CanvasDiagnosticApi[]
}

/**
 * One entry of a canvas's source-version history (metadata only —
 * fetch a version's files via `source?version_id=`).
 */
export interface CanvasVersionApi {
    /** The version's id. */
    id: string
    /**
     * The version this one was based on (null for the first publish).
     * @nullable
     */
    parent_version_id: string | null
    /**
     * Short description recorded with the publish.
     * @nullable
     */
    prompt: string | null
    /**
     * Task that published the version, when one did.
     * @nullable
     */
    task_id: string | null
    /** True for a staged draft version that has never been the canvas head; promote it to make it live. */
    draft: boolean
    readonly created_by: UserBasicApi | null
    /** When the version was published. */
    created_at: string
}

export interface PaginatedCanvasVersionListApi {
    count: number
    /** @nullable */
    next?: string | null
    /** @nullable */
    previous?: string | null
    results: CanvasVersionApi[]
}

/**
 * One registered action verb, as the host renders it before invoking.
 */
export interface CanvasActionDefinitionApi {
    /** The verb's registry name, e.g. 'annotations.create'. */
    verb: string
    /** One line naming what invoking the verb does. */
    summary: string
    /** True when the verb deletes or disables something; the host must confirm with the viewer first. */
    destructive: boolean
    /** Authoring docs for the verb: payload and result shape, behavior, and the confirmation copy it warrants. */
    usage: string
}

/**
 * The action registry: every verb a canvas may declare and invoke.
 */
export interface CanvasActionsResponseApi {
    /** Registered verbs, sorted by name. */
    actions: CanvasActionDefinitionApi[]
}

export type CanvasesListParams = {
    /**
     * Only return canvases in this channel.
     */
    channel?: string
    /**
     * Only return canvases of this kind. kind=component lists the component store.
     */
    kind?: CanvasesListKind
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
    /**
     * Only return canvases whose name or description contains this text (case-insensitive).
     */
    search?: string
}

export type CanvasesListKind = (typeof CanvasesListKind)[keyof typeof CanvasesListKind]

export const CanvasesListKind = {
    Component: 'component',
    Freeform: 'freeform',
    Grid: 'grid',
} as const

export type CanvasesBuildsRetrieveParams = {
    /**
     * Include the retained ready build for this historical source version.
     */
    version_id?: string
}

export type CanvasesDraftsRetrieveParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type CanvasesLayoutRetrieveParams = {
    /**
     * Read this historical layout version instead of the head (for version browsing).
     */
    version_id?: string
}

export type CanvasesSourceRetrieveParams = {
    /**
     * Read this historical source version instead of the head (for version browsing).
     */
    version_id?: string
}

export type CanvasesStateRetrieveParams = {
    /**
     * Only return entries in this scope.
     */
    scope?: CanvasesStateRetrieveScope
}

export type CanvasesStateRetrieveScope = (typeof CanvasesStateRetrieveScope)[keyof typeof CanvasesStateRetrieveScope]

export const CanvasesStateRetrieveScope = {
    Shared: 'shared',
    User: 'user',
} as const

export type CanvasesVersionsRetrieveParams = {
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}
