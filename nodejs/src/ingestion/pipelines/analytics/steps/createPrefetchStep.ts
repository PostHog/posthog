import { logger } from '~/common/utils/logger'
import { ChunkProcessingStep } from '~/ingestion/framework/base-chunk-pipeline'
import { ok } from '~/ingestion/framework/results'

export interface PrefetchStepOptions<T, K> {
    /** Stamped as the step's function name, which the framework uses for error attribution and metrics. */
    name: string
    /** Key to warm for an event. Return null to skip the event. */
    extractKey: (event: T) => K | null
    /** Batched load for the chunk's distinct keys. The result is discarded; the cache keeps it. */
    load: (keys: K[]) => Promise<unknown>
    enabled: boolean
}

/**
 * Builds a chunk step that warms a lazy-loader cache for all distinct keys in the
 * chunk with one batched load, instead of a single-key fetch per event when a later
 * sequential step reads the cache. Fire-and-forget: the lazy loader coalesces the
 * per-event lookups issued while this load is in flight onto the same promise, so
 * they fail together with it and the reading step handles the error. The catch only
 * keeps the discarded copy of the rejection from becoming an unhandled rejection.
 */
export function createPrefetchStep<T, K>(options: PrefetchStepOptions<T, K>): ChunkProcessingStep<T, T> {
    const { name, extractKey, load, enabled } = options

    const step: ChunkProcessingStep<T, T> = (events) => {
        if (enabled && events.length > 0) {
            const keys = new Set<K>()
            for (const event of events) {
                const key = extractKey(event)
                if (key !== null) {
                    keys.add(key)
                }
            }
            if (keys.size > 0) {
                void load([...keys]).catch((error) => {
                    // Recover only on an explicit retriable error. An unflagged error, such as a
                    // broken query, rethrows and crashes loudly rather than being masked.
                    if (error?.isRetriable === true) {
                        logger.warn('⚠️', `${name} failed on a retriable error`, { error: String(error) })
                        return
                    }
                    throw error
                })
            }
        }
        return Promise.resolve(events.map((event) => ok(event)))
    }

    Object.defineProperty(step, 'name', { value: name })
    return step
}
