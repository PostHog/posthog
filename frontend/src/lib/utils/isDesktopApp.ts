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

/** Desktop app on macOS: the window has no title bar, so the layout reserves space for the traffic lights. */
export function isDesktopAppMac(): boolean {
    return isDesktopApp() && window.__POSTHOG_DESKTOP__?.platform === 'darwin'
}

const FRESH_WINDOW_PARAM = '__posthogDesktopFreshWindow'
const FRESH_WINDOW_SESSION_KEY = 'posthog-desktop-fresh-window'

/**
 * The desktop app's main process appends `__posthogDesktopFreshWindow=1` to URLs it opens in
 * additional windows ("open in new window", File → New window). Called once at boot, before
 * kea-router initializes: moves the flag into sessionStorage (per-window, survives reloads)
 * and strips it from the URL so scenes never see it.
 */
export function consumeDesktopFreshWindowParam(): void {
    if (!isDesktopApp()) {
        return
    }
    try {
        const url = new URL(window.location.href)
        if (url.searchParams.has(FRESH_WINDOW_PARAM)) {
            url.searchParams.delete(FRESH_WINDOW_PARAM)
            sessionStorage.setItem(FRESH_WINDOW_SESSION_KEY, '1')
            window.history.replaceState(window.history.state, '', url.toString())
        }
    } catch {
        // URL parsing or sessionStorage unavailable; the window just behaves like the primary one
    }
}

/** Whether this window was opened as an additional desktop window (single tab + pinned tabs, no tab persistence). */
export function isDesktopFreshWindow(): boolean {
    try {
        return isDesktopApp() && sessionStorage.getItem(FRESH_WINDOW_SESSION_KEY) === '1'
    } catch {
        return false
    }
}
