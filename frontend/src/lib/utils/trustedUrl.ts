import { getAppContext } from 'lib/utils/getAppContext'

/**
 * Whether a URL is trusted enough to load or link to from within untrusted content.
 * Trusted = served from PostHog itself: same-origin (incl. relative URLs), any `posthog.com` host, or the
 * configured uploaded media origin.
 * Anything else (including `data:`/`blob:` URIs) is untrusted.
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
    if (parsed.hostname === window.location.hostname || /(^|\.)posthog\.com$/i.test(parsed.hostname)) {
        return true
    }
    return isUploadedMediaOrigin(parsed)
}

function isUploadedMediaOrigin(parsed: URL): boolean {
    const mediaOrigin = getAppContext()?.uploaded_media_origin
    if (!mediaOrigin) {
        return false
    }
    try {
        return parsed.origin === new URL(mediaOrigin).origin
    } catch {
        return false
    }
}
