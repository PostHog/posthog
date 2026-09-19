import posthog from 'posthog-js'

/**
 * A stale-deploy chunk stays gone for the life of the page, so every remount of the subtree that
 * needs it throws the same failure again. A streaming view can remount many times a second, so
 * report one per page load: each report carries the same fact, and the flood buries everything else.
 */
let reported = false

export function reportChunkLoadError(error: unknown, teamId?: number | null): void {
    if (reported) {
        return
    }
    reported = true
    posthog.captureException(error, { chunk_load_error: true, team_id: teamId })
}
