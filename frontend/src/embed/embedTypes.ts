/**
 * The contract between the embedded web app and the shell that hosts it. The desktop shell
 * (products/desktop, a separate workspace) keeps its own copy of these shapes, so a breaking change
 * here must bump EMBED_API_VERSION, and the host must check the version it gets back.
 */
export const EMBED_API_VERSION = 1

export interface EmbedLocation {
    pathname: string
    search: string
    hash: string
}

export interface EmbedHost {
    /** The region's API host, for example `https://us.posthog.com`. */
    backendHost: string
    /** Synchronous because the API client reads it for each request. The host keeps a fresh token ready. */
    getAccessToken: () => string
    /** Called on a 401. Resolves to the new token, or null when the session has ended. */
    refreshAccessToken: () => Promise<string | null>
    /** The app's own location inside the host, for example `/project/2/insights`. */
    getLocation: () => EmbedLocation
    /** The app navigated. The host moves its own URL so back, forward and reload keep working. */
    navigate: (url: string, options: { replace: boolean }) => void
    signOut: () => void
    theme: 'light' | 'dark'
    /** The project key and host that the web app reports to. Without it, capture and feature flags stay off. */
    analytics?: { apiKey: string; apiHost: string }
}

export interface EmbedHandle {
    apiVersion: number
    /** Call after the host changes the app's location. Back and forward need no call. */
    syncLocation: () => void
    setTheme: (theme: EmbedHost['theme']) => void
    unmount: () => void
}
