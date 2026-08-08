import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { DESKTOP_SCHEME } from './desktopScheme'

const DESKTOP_DOWNLOAD_URL = 'https://posthog.com/code'

// How long to wait for the OS to hand off to a native app before we treat the scheme as
// unhandled. Long enough to clear the browser's "Open PostHog Desktop?" confirmation on a
// normal click, short enough that the fallback still feels like a response to the click.
const HANDOFF_GRACE_MS = 2500

export interface OpenDeepLinkOptions {
    /** Toast body shown when nothing handled the link. */
    missingMessage: string
    /** When set, the toast offers a button that opens this URL (e.g. an app download page). */
    downloadUrl?: string
    downloadLabel?: string
}

/**
 * Open a custom-scheme deep link and give the user feedback when nothing handles it.
 *
 * A browser can't report whether a custom scheme has a registered handler, so a bare
 * `window.open('posthog-code://…')` does nothing visible when the app isn't installed —
 * the click is dead. We fire the link, then watch for the tab losing visibility or focus,
 * which is what happens when the OS switches to the native app. If the tab is still in the
 * foreground after a short grace period, we assume no handler and surface a fallback toast.
 */
export function openDeepLinkWithFallback(deepLink: string, options: OpenDeepLinkOptions): void {
    let handedOff = false
    const markHandedOff = (): void => {
        handedOff = true
    }

    // The tab is hidden or blurred once the OS brings the native app to the foreground.
    document.addEventListener('visibilitychange', markHandedOff, { once: true })
    window.addEventListener('blur', markHandedOff, { once: true })
    window.addEventListener('pagehide', markHandedOff, { once: true })

    window.open(deepLink, '_blank')

    window.setTimeout(() => {
        document.removeEventListener('visibilitychange', markHandedOff)
        window.removeEventListener('blur', markHandedOff)
        window.removeEventListener('pagehide', markHandedOff)

        if (handedOff || document.hidden) {
            return
        }

        lemonToast.info(options.missingMessage, {
            button: options.downloadUrl
                ? {
                      label: options.downloadLabel ?? 'Download',
                      action: () => {
                          window.open(options.downloadUrl, '_blank')
                      },
                  }
                : undefined,
        })
    }, HANDOFF_GRACE_MS)
}

/**
 * Open a fully-built PostHog Desktop deep link (`posthog-code(-dev)://…`), falling back to
 * a toast that points at the download page when the app isn't installed.
 */
export function openDesktopDeepLink(deepLink: string): void {
    openDeepLinkWithFallback(deepLink, {
        missingMessage: "PostHog Desktop didn't open. Install it to continue.",
        downloadUrl: DESKTOP_DOWNLOAD_URL,
        downloadLabel: 'Download the app',
    })
}

/**
 * Open a PostHog Desktop deep link by path (`posthog-code(-dev)://<path>`). `path` is the
 * part after the scheme, e.g. `task/<id>` or `new?prompt=…`.
 */
export function openDesktopApp(path: string): void {
    openDesktopDeepLink(`${DESKTOP_SCHEME}://${path}`)
}
