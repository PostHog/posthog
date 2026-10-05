import { isAccessDeniedError } from 'lib/api-error'

/**
 * Two panels load alongside a recording: notebook comments and experiment context. Each one fires
 * its own request every time a recording is opened, so a viewer without access to the resource
 * behind a panel repeats the same denied request for every recording they open — working through a
 * list turns into a run of 403s, and the panel stays empty either way.
 *
 * Access cannot change without a page load, so the first denial is remembered and the request is
 * skipped from then on. It is held per project, because the same viewer can have access in one
 * project and not in the next one they switch to.
 */
export type RecordingSidecarResource = 'notebook-comments' | 'experiment-context'

const deniedProjectsByResource = new Map<RecordingSidecarResource, Set<string>>()

export function isRecordingSidecarAccessDenied(
    resource: RecordingSidecarResource,
    projectId: string | number | null | undefined
): boolean {
    if (projectId == null) {
        return false
    }
    return Boolean(deniedProjectsByResource.get(resource)?.has(String(projectId)))
}

/**
 * Remembers an access denial only. Every other failure — a transient gateway error, a timeout, a
 * feature-flag gate that can still flip on — stays retryable, so a panel is never suppressed by
 * something that may succeed on the next recording.
 */
export function rememberRecordingSidecarAccessDenial(
    resource: RecordingSidecarResource,
    projectId: string | number | null | undefined,
    error: unknown
): void {
    if (projectId == null || error === null || typeof error !== 'object') {
        return
    }
    if (!isAccessDeniedError(error as { status?: number; code?: string | null })) {
        return
    }
    const denied = deniedProjectsByResource.get(resource) ?? new Set<string>()
    denied.add(String(projectId))
    deniedProjectsByResource.set(resource, denied)
}

/** The memo deliberately outlives any single logic's mount, so tests need a way to clear it. */
export function resetRecordingSidecarAccessDenials(): void {
    deniedProjectsByResource.clear()
}
