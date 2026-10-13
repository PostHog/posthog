import type { CanvasBuildApi, CanvasBuildsResponseApi, CanvasDiagnosticApi } from '../generated/api.schemas'

// Reads over a canvas's build lifecycle, ported from PostHog Desktop's canvasBuildSchemas.ts.

/** The build still queued or building, if any. */
export function activeCanvasBuild(lifecycle: CanvasBuildsResponseApi): CanvasBuildApi | null {
    return (
        lifecycle.builds.find((build) => build.build_status === 'queued' || build.build_status === 'building') ?? null
    )
}

/** The newest finished build. */
export function latestFinishedCanvasBuild(lifecycle: CanvasBuildsResponseApi): CanvasBuildApi | null {
    return lifecycle.builds.find((build) => build.build_status === 'ready' || build.build_status === 'failed') ?? null
}

/**
 * The failed build of the canvas's current head, if its latest attempt failed. It matters even
 * when an older live or pinned build comes first in the list, so this matches by version, not position.
 */
export function currentHeadBuildFailure(lifecycle: CanvasBuildsResponseApi): CanvasBuildApi | null {
    if (!lifecycle.current_version_id) {
        return null
    }
    const latestAttempt = lifecycle.builds.find((build) => build.source_version_id === lifecycle.current_version_id)
    return latestAttempt?.build_status === 'failed' ? latestAttempt : null
}

/** The top error diagnostics, one line each, for a tooltip. */
export function topBuildErrors(diagnostics: CanvasDiagnosticApi[]): string[] {
    return diagnostics
        .filter((diagnostic) => diagnostic.severity === 'error')
        .slice(0, 3)
        .map((diagnostic) =>
            diagnostic.path
                ? `${diagnostic.path}${diagnostic.line ? `:${diagnostic.line}` : ''}: ${diagnostic.message}`
                : diagnostic.message
        )
}

export function formatBuildElapsed(ms: number): string {
    const seconds = Math.max(0, Math.floor(ms / 1000))
    if (seconds < 60) {
        return `${seconds}s`
    }
    const minutes = Math.floor(seconds / 60)
    if (minutes < 60) {
        return `${minutes}m ${seconds % 60}s`
    }
    return `${Math.floor(minutes / 60)}h ${minutes % 60}m`
}
