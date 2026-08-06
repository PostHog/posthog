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
    readonly created_by: UserBasicApi
    readonly created_at: string
    readonly updated_at: string
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
    /** Whether the canvas is pinned in its channel. */
    pinned?: boolean
    /**
     * Task currently generating this canvas, or null to clear it.
     * @nullable
     */
    generation_task_id?: string | null
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
 * Exact-version dependencies, restricted to the platform-supported set (react, react-dom, @posthog/quill, recharts, lucide-react, dayjs) at their pinned versions.
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
    /** Exact-version dependencies, restricted to the platform-supported set (react, react-dom, @posthog/quill, recharts, lucide-react, dayjs) at their pinned versions. */
    dependencies?: CanvasSourceProjectApiDependencies
    /** Version of the host-injected `ph` canvas SDK the project targets. */
    canvasSdkVersion?: string
    /** Bounded capabilities frozen into the built artifact. Declare every insight short id the canvas loads, every event it captures, and inlineQueries when it runs ad-hoc HogQL — the host enforces these at runtime and validation rejects undeclared `ph` calls. */
    capabilities?: CanvasCapabilitiesApi
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

export type CanvasesListParams = {
    /**
     * Only return canvases in this channel.
     */
    channel?: string
    /**
     * Number of results to return per page.
     */
    limit?: number
    /**
     * The initial index from which to return the results.
     */
    offset?: number
}

export type CanvasesBuildsRetrieveParams = {
    /**
     * Include the retained ready build for this historical source version.
     */
    version_id?: string
}

export type CanvasesSourceRetrieveParams = {
    /**
     * Read this historical source version instead of the head (for version browsing).
     */
    version_id?: string
}

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
