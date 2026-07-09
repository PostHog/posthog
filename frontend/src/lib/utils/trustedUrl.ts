/**
 * Whether a URL is trusted enough to load or link to from within untrusted content.
 * Trusted = served from PostHog itself: same-origin (incl. relative URLs) or any `posthog.com` host.
 * Anything else (including `data:`/`blob:` URIs) is untrusted.
 *
 * Kept dependency-free: it's imported from both lemon-ui and scene code, so any import added here
 * ends up in every chunk that renders markdown or an insight error state.
 */
export function isTrustedPostHogUrl(url: string | undefined): boolean {
    if (!url) {
        return false
    }
    let parsed: URL
    try {
        parsed = new URL(url, window.location.origin)
    } catch {
        return false
    }
    if (parsed.protocol !== 'https:' && parsed.protocol !== 'http:') {
        return false
    }
    return parsed.hostname === window.location.hostname || /(^|\.)posthog\.com$/i.test(parsed.hostname)
}
