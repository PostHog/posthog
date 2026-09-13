import { useCallback, useEffect, useState } from 'react'

/** How long the desktop app gets to take over before the visitor is offered a way out. */
export const HANDOFF_GRACE_MS = 2500

export type DesktopHandoffStatus = 'opening' | 'stalled'

export interface DesktopHandoff {
    status: DesktopHandoffStatus
    /** Undefined when there is no link to fire. */
    retry?: () => void
}

/**
 * Fires a `<scheme>://…` desktop deep link and reports whether the visitor is still here
 * afterwards. A browser never tells a page whether a custom scheme has a handler, so an
 * uninstalled app makes the navigation a no-op: without this timer the page waits forever on
 * "Opening…" and every further click repeats the same invisible no-op. `retry` fires the link
 * again and returns the status to `opening`, so a click always changes something on screen.
 */
export function useDesktopHandoff(deepLink: string | null): DesktopHandoff {
    const [attempt, setAttempt] = useState(0)
    const [status, setStatus] = useState<DesktopHandoffStatus>('opening')

    useEffect(() => {
        if (!deepLink) {
            return
        }
        setStatus('opening')
        const timeout = window.setTimeout(() => setStatus('stalled'), HANDOFF_GRACE_MS)
        window.location.href = deepLink
        return () => window.clearTimeout(timeout)
    }, [deepLink, attempt])

    const retry = useCallback(() => setAttempt((previous) => previous + 1), [])

    return { status, retry: deepLink ? retry : undefined }
}
