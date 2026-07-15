/**
 * Whether the frontend is running inside the PostHog desktop app (products/desktop).
 * The desktop app's local server injects `window.__POSTHOG_DESKTOP__` into index.html.
 */
export function isDesktopApp(): boolean {
    return typeof window !== 'undefined' && !!window.__POSTHOG_DESKTOP__
}

export function getDesktopAppVersion(): string | null {
    return (typeof window !== 'undefined' && window.__POSTHOG_DESKTOP__?.version) || null
}
