import { captureViaBeacon } from 'lib/utils/captureViaBeacon'

export const APP_RELOAD_EVENT = 'app reloaded after failed import'

/** Which recovery path reloaded the page. */
export type AppReloadReason = 'chunk_load_error_boundary' | 'scene_import_error'

/**
 * Records that the app reloaded itself to recover from a failed lazy import, which is what a
 * stale deploy does to a long-lived tab. The reload discards whatever the user had open, so
 * without this event the only trace of it is a session recording.
 *
 * Do not import posthog-js here. This module is reachable from the entry chunk, and the SDK
 * lives in the App chunk that the chunk-load boundary guards. `window.posthog` is set once the
 * SDK has initialized, and the beacon covers the boot case where it has not.
 */
export function captureAppReload(reason: AppReloadReason, error: unknown): void {
    try {
        const err = error && typeof error === 'object' ? (error as { name?: string; message?: string }) : null
        const properties = {
            reason,
            error_name: err?.name ?? 'unknown',
            error_message: typeof err?.message === 'string' ? err.message : String(error),
        }
        // sendBeacon because the caller reloads in the same tick, which cancels an XHR or a fetch.
        if (window.posthog) {
            window.posthog.capture(APP_RELOAD_EVENT, properties, { send_instantly: true, transport: 'sendBeacon' })
        } else {
            captureViaBeacon(APP_RELOAD_EVENT, properties)
        }
    } catch {
        // Both callers reload on the next line, so losing the event beats canceling the recovery.
    }
}
