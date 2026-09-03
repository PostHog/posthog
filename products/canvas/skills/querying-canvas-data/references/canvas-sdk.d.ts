// Typed surface of `@posthog/canvas-sdk`, the `ph` bridge, for canvas authors
// and authoring agents. Reference only: nothing type-checks against it, and the
// methods are served by the host over postMessage, so this describes the
// protocol rather than implementing it. The implementation is
// products/canvas/packages/canvas_builder/canvas-sdk.mjs.
//
// A published canvas is held to `project.capabilities` at runtime: every insight
// short id, capture event name, state scope, action verb, and connector tool must
// be declared, and ad-hoc `ph.query` needs `inlineQueries: true`.

/**
 * One trends-style series. `ph.loadInsight` and a typed query node return these
 * as `results` (see CanvasDataResult), so cast when you know the query kind.
 */
export interface CanvasSeriesResult {
    /** Per-interval values, aligned with `days`. */
    data: number[]
    /** ISO dates for each interval. */
    days: string[]
    /** Human labels for each interval. */
    labels: string[]
    /** Sum across the window, which is the usual KPI total. */
    count?: number
    /** Single-value total for aggregated displays. */
    aggregated_value?: number
    /** Series label. */
    label?: string
    /** Set when the query has a compare period; match on this, never on index. */
    compare_label?: 'current' | 'previous'
}

/**
 * Result of `ph.loadInsight` and `ph.query`. The element shape depends on the
 * query kind, which is why `results` is not narrowed here:
 * - Trends-style (typed insight nodes): series objects, so cast to
 *   `CanvasSeriesResult[]`. `columns` is empty.
 * - SQL: rows, each an array of cell values in `columns` order.
 * Funnels, retention, and paths return their own PostHog-native shapes.
 */
export interface CanvasDataResult {
    columns: string[]
    results: unknown[]
}

export interface CanvasDateRange {
    date_from?: string | null
    date_to?: string | null
}

export interface CanvasLoadInsightOptions {
    /** Re-scope the saved insight to this window (a saved SQL insight may ignore it). */
    dateRange?: CanvasDateRange
    /**
     * Values for a SQL insight's `{variables.name}` placeholders, keyed by code
     * name. The host rejects a variable the insight doesn't use.
     */
    variables?: Record<string, unknown>
    /** Cache lifetime in whole seconds, 30–86400. */
    refresh?: number
}

export interface CanvasQueryOptions {
    /** Cache lifetime in whole seconds, 30–86400. */
    refresh?: number
}

/** "user" (default) is private to the viewer; "shared" is one value per canvas, team-visible. */
export type CanvasStateScope = 'user' | 'shared'

export interface CanvasStateEntry {
    scope: CanvasStateScope
    key: string
    value: unknown
    updatedAt?: string
}

export interface CanvasState {
    /** Resolves to the stored JSON value, or null when unset. */
    get(key: string, options?: { scope?: CanvasStateScope }): Promise<unknown>
    /**
     * Stores a JSON value (64 KB serialized cap, 256 keys per scope). Setting
     * null deletes the key.
     */
    set(key: string, value: unknown, options?: { scope?: CanvasStateScope }): Promise<{ ok: boolean }>
    list(options?: { scope?: CanvasStateScope }): Promise<CanvasStateEntry[]>
}

export interface CanvasActions {
    /**
     * Write into PostHog as the viewer; the result shape depends on the verb.
     * Every verb must be declared in `capabilities.posthog.actions`, and calls
     * belong on an explicit user gesture (a button), never on load or render.
     */
    invoke(verb: string, payload?: Record<string, unknown>): Promise<unknown>
}

export type CanvasConnectorCallStatus =
    | 'ok'
    | 'not_connected'
    | 'needs_reauth'
    | 'blocked'
    | 'tool_missing'
    | 'write_blocked'
    | 'upstream_error'

export interface CanvasConnectorCallResult {
    status: CanvasConnectorCallStatus
    /** The tool output when status is "ok"; MCP tools return { content, structured_content, is_error }. */
    result: Record<string, unknown> | null
    /** Human-readable explanation for a non-ok status. */
    detail: string
    /** True when the result exceeded the size cap and was cut to a preview. */
    truncated: boolean
    /** Settings path where the viewer connects the provider, when that would help. */
    connect_path: string | null
}

export interface CanvasConnectorCallOptions {
    /** Cache lifetime in whole seconds, 30–86400. Defaults to 60. */
    refresh?: number
}

export interface CanvasConnectors {
    /**
     * Read live third-party data with the viewer's own connection. `provider` is
     * "github" or "mcp:<server host>"; declare every provider and tool in
     * `capabilities.connectors`. Never rejects for a missing connection: check
     * `status` and offer `connect(provider)`.
     */
    call(
        provider: string,
        tool: string,
        args?: Record<string, unknown>,
        options?: CanvasConnectorCallOptions
    ): Promise<CanvasConnectorCallResult>
    /** Open the settings page where the viewer connects the provider. Call from a click. */
    connect(provider: string): void
}

export interface CanvasAgentRequestResult {
    requestOutcome: 'signaled' | 'new_run' | 'already_queued' | 'reported'
    taskId: string
}

export interface CanvasAgent {
    /**
     * Ask the canvas's authoring agent for a change. The host shows the exact
     * prompt and asks the viewer to approve before anything is dispatched.
     * Requires `capabilities.posthog.agentRequests`.
     */
    request(prompt: string): Promise<CanvasAgentRequestResult>
}

/** In-app navigation. Only these four targets exist. */
export interface CanvasNavigate {
    toTask(taskId: string): void
    toNewTask(): void
    toCanvas(canvasId: string): void
    toNewCanvas(): void
}

export interface CanvasSdk {
    /**
     * PREFERRED data path: load a saved insight by short id and render its stored
     * result. Declare the short id in `capabilities.posthog.insights`.
     */
    loadInsight(shortId: string, options?: CanvasLoadInsightOptions): Promise<CanvasDataResult>
    /**
     * Run a typed query node (`{ kind: "TrendsQuery", … }`, preferred, because numbers
     * match the PostHog UI) or an inline HogQL string (escape hatch). Requires
     * `capabilities.posthog.inlineQueries` in a published canvas.
     */
    query(
        query: Record<string, unknown> | string,
        params?: Record<string, unknown>,
        options?: CanvasQueryOptions
    ): Promise<CanvasDataResult>
    /**
     * Send an analytics event (properties capped at 16 KB serialized). Declare
     * each event name in `capabilities.posthog.captureEvents`.
     */
    capture(event: string, properties?: Record<string, unknown>, distinctId?: string): Promise<{ ok: boolean }>
    /** Open a PostHog URL externally. https://posthog.com / *.posthog.com only. */
    openExternal(url: string): void
    state: CanvasState
    actions: CanvasActions
    agent: CanvasAgent
    connectors: CanvasConnectors
    /**
     * Frozen per-placement config parsed at boot. Published/component runtime
     * only; undefined in the edit-mode preview.
     */
    config?: Readonly<Record<string, unknown>>
    /** Preview runtime only today; undefined in a published canvas. */
    navigate?: CanvasNavigate
}

/**
 * The canvas's PostHog bridge, the same object as the `window.ph` global. Both
 * are installed on the document, so a `?worker` bundle cannot reach them.
 */
export declare const ph: CanvasSdk
declare const defaultPh: CanvasSdk
export default defaultPh
