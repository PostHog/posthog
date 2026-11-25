import posthog from 'posthog-js'

import { ApiError, isAbortError } from 'lib/api'
import { shouldReportApiFailure } from 'lib/api-error'

import type { LoadFailure } from '../trace/types'

export function toLoadFailure(error: unknown): LoadFailure {
    return error instanceof ApiError && error.status === 404 ? 'not_found' : 'failed'
}

/** Settles a read into its value or its failure, and reports a failure worth reporting without showing a toast. */
export async function readOrFailure<T>(request: Promise<T>): Promise<{ value: T } | { failure: LoadFailure }> {
    try {
        return { value: await request }
    } catch (error) {
        const failure = toLoadFailure(error)
        if (failure === 'failed' && !isAbortError(error) && shouldReportApiFailure(error)) {
            posthog.captureException(error)
        }
        return { failure }
    }
}

// Ids come from SDKs and URLs, so they can be any string. A plain object keyed by them returns an inherited member for
// an id such as `constructor`, so state keyed by them is kept in maps.
export function noEntries<V>(): ReadonlyMap<string, V> {
    return new Map()
}
