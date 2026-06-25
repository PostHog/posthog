interface NavigatorLike {
    userAgent: string
    platform?: string
    maxTouchPoints?: number
}

/**
 * Best-effort detection of WebKit-based browsers: Safari on macOS and *every* browser on iOS/iPadOS
 * (iOS forces all browsers onto WebKit).
 *
 * Used to avoid programmatically firing a modal WebAuthn ceremony without a user gesture — WebKit
 * hangs the page in that case, while Chromium/Gecko tolerate it. Intentionally fail-safe: a wrong
 * answer in either direction only changes whether the passkey prompt auto-opens; the explicit
 * passkey button always works, so login is never broken.
 */
export function isWebKitBrowser(
    nav: NavigatorLike | undefined = typeof navigator !== 'undefined' ? navigator : undefined
): boolean {
    if (!nav?.userAgent) {
        return false
    }
    const ua = nav.userAgent

    // iOS / iPadOS — every browser is WebKit. iPadOS in desktop mode reports as Mac, so fall back to
    // the touch-points heuristic.
    const isIOS = /iPad|iPhone|iPod/.test(ua) || (nav.platform === 'MacIntel' && (nav.maxTouchPoints ?? 0) > 1)
    if (isIOS) {
        return true
    }

    // Safari on macOS — AppleWebKit + Safari, but not a Chromium/Gecko browser (which also carry the
    // Safari token). CriOS/FxiOS/EdgiOS are iOS browsers already caught above; excluded here for safety.
    return (
        /AppleWebKit/.test(ua) &&
        /Safari/.test(ua) &&
        !/Chrome|Chromium|Android|CriOS|FxiOS|EdgiOS|Edg\/|OPR\//.test(ua)
    )
}
