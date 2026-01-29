import { BatchPipeline } from '../batch-pipeline.interface'
import { isOkResult } from '../results'

/**
 * Consumes all results from a batch pipeline, advancing fake timers as needed.
 * Returns a flat array of all OK values.
 *
 * This helper handles the correct pattern for testing pipelines with Jest fake timers:
 * 1. Start consuming results (without blocking)
 * 2. Advance timers to allow processing to complete
 * 3. Await and return all collected values
 *
 * @param pipeline - The batch pipeline to consume from
 * @param advanceTimeMs - How much time to advance (should be >= longest processing time)
 * @returns Array of OK result values
 */
export async function consumeAll<T>(pipeline: BatchPipeline<unknown, T, unknown>, advanceTimeMs: number): Promise<T[]> {
    const resultsPromise = (async () => {
        const allValues: T[] = []
        let results = await pipeline.next()
        while (results) {
            for (const r of results) {
                if (isOkResult(r.result)) {
                    allValues.push(r.result.value)
                }
            }
            results = await pipeline.next()
        }
        return allValues
    })()

    await jest.advanceTimersByTimeAsync(advanceTimeMs)
    return resultsPromise
}

/**
 * Consumes all results from a batch pipeline, preserving the batch structure.
 * Returns an array of batches, where each batch is an array of OK values.
 *
 * Useful for testing how pipelines stream results (one at a time vs all at once).
 *
 * Note: When using fake timers, start this promise first, then advance timers,
 * then await the result.
 *
 * @param pipeline - The batch pipeline to consume from
 * @returns Promise of array of batches, each batch is an array of OK result values
 */
export async function collectBatches<T>(pipeline: BatchPipeline<unknown, T, unknown>): Promise<T[][]> {
    const batches: T[][] = []
    let results = await pipeline.next()
    while (results) {
        const batch: T[] = []
        for (const r of results) {
            if (isOkResult(r.result)) {
                batch.push(r.result.value)
            }
        }
        batches.push(batch)
        results = await pipeline.next()
    }
    return batches
}
