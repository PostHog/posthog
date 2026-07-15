import { Node } from '~/queries/schema/schema-general'

/** Options accepted by `window.PostHogWidgets.mountQueryEditor`. */
export interface MountQueryEditorOptions {
    /** The query node to edit (e.g. an InsightVizNode, or a bare source node). Plain JSON. */
    query: Node | Record<string, any>
    /** Called with the full updated query node (plain JSON) on every edit. */
    onQueryChange?: (query: Node) => void
    /** Absolute API host, e.g. "https://us.posthog.com". */
    apiHost: string
    /**
     * Async access-token source. Called once at mount for the initial token and again
     * whenever a request 401s (the host should refresh and return a new token).
     * Preferred over `personalApiKey`.
     */
    getAccessToken?: () => Promise<string | null>
    /** Static token fallback (personal API key or OAuth access token). */
    personalApiKey?: string
    /** Theme; defaults to "light". */
    theme?: 'light' | 'dark'
    /** Optional callback for a "close" affordance rendered by the widget shell. */
    onClose?: () => void
    /**
     * HARNESS/TEST ONLY: seed userLogic/teamLogic with fixed data instead of loading
     * them from the API. Lets the editor UI render without credentials (all taxonomy /
     * query requests will still fail). Never use in production hosts.
     */
    __unsafeMockContext?: {
        user: Record<string, any>
        team: Record<string, any>
    }
}

export interface QueryEditorWidgetHandle {
    update(props: Partial<Pick<MountQueryEditorOptions, 'query' | 'onQueryChange' | 'theme'>>): void
    unmount(): void
}
