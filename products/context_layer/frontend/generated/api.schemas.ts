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
 * Response shape for a channel's page identity in the wiki.
 */
export interface ChannelWikiPageApi {
    /** Repo-relative path of the wiki page whose frontmatter names the channel. */
    path: string
    /** Whether a page exists at this path. False when the path is a proposal for a channel whose page has not been created yet. */
    exists?: boolean
}

/**
 * Request body for landing agent commits posted back as a git bundle.
 */
export interface CommitBundleApi {
    /** A `git bundle` carrying the ref to land, created in the agent's clone (for example `git bundle create out.bundle origin/main..main`). */
    bundle: string
    /**
     * Optional run summary stored in the landed commit body.
     * @maxLength 10000
     */
    summary?: string
    /**
     * Land a dated dreaming branch (`dream/<YYYY-MM-DD>`) as one merge commit instead of rebasing onto `main`. Omit for ordinary commits on `main`.
     * @maxLength 64
     * @nullable
     */
    branch?: string | null
}

/**
 * Response shape for the wiki's current state.
 */
export interface ContextLayerStatusApi {
    /** Commit sha of the wiki's current head. */
    head_sha: string
}

/**
 * 400 body when a write violates the wiki's structure rules.
 */
export interface LintErrorApi {
    /** What was rejected. */
    detail: string
    /** One entry per structure violation found by the linter. */
    errors: string[]
}

/**
 * Response shape for a wiki bundle export.
 */
export interface WikiExportApi {
    /** Short-lived download URL for the wiki's current bundle. */
    url: string
    /** Commit sha of the bundle behind the URL. */
    head_sha: string
}

/**
 * Response shape for one wiki page.
 */
export interface WikiPageApi {
    /** Repo-relative path of the page, for example `areas/analytics.md`. */
    path: string
    /** The page's Markdown content. */
    content: string
    /** Commit sha the content was read at; pass back as `base_head` on writes. */
    head_sha: string
    /** When this page was last changed in the wiki history. */
    updated_at: string
}

/**
 * Request body for creating or replacing one wiki page.
 */
export interface WikiPageWriteApi {
    /**
     * Repo-relative Markdown path inside the wiki's structure, for example `projects/12/spaces/general.md`.
     * @maxLength 512
     */
    path: string
    /**
     * The complete Markdown content for the page.
     * @maxLength 1000000
     */
    content: string
    /**
     * Optimistic-concurrency guard: the head sha the edit is based on. A moved head is rejected with 409 and the current head; omit to write unguarded.
     * @nullable
     */
    base_head?: string | null
}

/**
 * 409 body when a guarded write was based on a stale head.
 */
export interface HeadConflictApi {
    /** What moved and what to do next. */
    detail: string
    /** The wiki's current head sha; re-read pages at this head and retry. */
    current_head: string
}

/**
 * Response shape for the wiki's page listing.
 */
export interface WikiTreeApi {
    /** Commit sha of the wiki's current head. */
    head_sha: string
    /** Repo-relative path of every Markdown page at the current head. */
    paths: string[]
}

export interface WikiHealthFindingApi {
    /** Stable category used to group this finding. */
    category: string
    /** Wiki page path associated with this finding. */
    path: string
    /** Human-readable explanation of the finding. */
    message: string
}

export interface WikiHealthReportApi {
    /** Commit sha inspected by the report. */
    head_sha: string
    /** Health findings for the current wiki head. */
    findings: WikiHealthFindingApi[]
}

export type ContextLayerPagesRetrieveParams = {
    /**
     * Repo-relative Markdown path of the page to read.
     */
    path: string
}

export type ContextLayerAgentPagesRetrieveParams = {
    /**
     * Repo-relative Markdown path of the page to read.
     */
    path: string
}
