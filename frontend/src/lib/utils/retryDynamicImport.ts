import { isChunkLoadError } from 'lib/utils/isChunkLoadError'

/** A dynamic `import()` of an ES module, e.g. `() => import('./SomeScene')`. */
export type DynamicImporter<T> = () => Promise<T>

interface RetryOptions {
    /** Number of *additional* attempts after the first one fails. Defaults to 2 (3 attempts total). */
    retries?: number
    /** Base delay before the first retry; subsequent retries back off exponentially. Defaults to 250ms. */
    baseDelayMs?: number
}

const wait = (ms: number): Promise<void> => new Promise((resolve) => setTimeout(resolve, ms))

/**
 * Wraps a lazy `import()` so a transient fetch failure (flaky network, a CDN edge
 * blip) is retried with exponential backoff before the rejection bubbles up.
 *
 * Without this a single dropped request while fetching a code-split scene chunk
 * leaves the scene unmounted — a blank screen plus an unhandled `TypeError:
 * Failed to fetch`. Retrying recovers from the common transient case.
 *
 * Only network-shaped failures are retried; a genuine module-evaluation error is
 * deterministic, so we fail fast rather than waiting through pointless backoff.
 * Persistent chunk-hash mismatches after a deploy still surface to sceneLogic's
 * reload handling once retries are exhausted.
 */
export async function retryDynamicImport<T>(
    importer: DynamicImporter<T>,
    { retries = 2, baseDelayMs = 250 }: RetryOptions = {}
): Promise<T> {
    let lastError: unknown
    for (let attempt = 0; attempt <= retries; attempt++) {
        try {
            return await importer()
        } catch (error) {
            lastError = error
            if (attempt === retries || !isRetriableImportError(error)) {
                break
            }
            await wait(baseDelayMs * 2 ** attempt)
        }
    }
    throw lastError
}

function isRetriableImportError(error: unknown): boolean {
    if (isChunkLoadError(error)) {
        return true
    }
    // A bare `TypeError: Failed to fetch` is the network-layer failure underlying
    // most chunk-load errors; it is not matched by isChunkLoadError (which targets
    // the module-specific messages) but is still worth retrying here.
    const message = error instanceof Error ? error.message : ''
    return message.includes('Failed to fetch')
}
