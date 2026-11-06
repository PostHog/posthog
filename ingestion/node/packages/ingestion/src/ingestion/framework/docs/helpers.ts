import { ChunkPipeline } from '~/ingestion/framework/chunk-pipeline.interface'
import { isOkResult } from '~/ingestion/framework/results'

/**
 * Consumes all results from a chunk pipeline, advancing fake timers as needed.
 * Returns a flat array of all OK values.
 *
 * This helper handles the correct pattern for testing pipelines with Jest fake timers:
 * 1. Start consuming results (without blocking)
 * 2. Advance timers to allow processing to complete
 * 3. Await and return all collected values
 *
 * @param pipeline - The chunk pipeline to consume from
 * @param advanceTimeMs - How much time to advance (should be >= longest processing time)
 * @returns Array of OK result values
 */
export async function consumeAll<T>(pipeline: ChunkPipeline<unknown, T, unknown>, advanceTimeMs: number): Promise<T[]> {
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
 * Consumes all results from a chunk pipeline, preserving the chunk structure.
 * Returns an array of chunks, where each chunk is an array of OK values.
 *
 * Useful for testing how pipelines stream results (one at a time vs all at once).
 *
 * Note: When using fake timers, start this promise first, then advance timers,
 * then await the result.
 *
 * @param pipeline - The chunk pipeline to consume from
 * @returns Promise of array of chunks, each chunk is an array of OK result values
 */
export async function collectChunks<T>(pipeline: ChunkPipeline<unknown, T, unknown>): Promise<T[][]> {
    const chunks: T[][] = []
    let results = await pipeline.next()
    while (results) {
        const chunk: T[] = []
        for (const r of results) {
            if (isOkResult(r.result)) {
                chunk.push(r.result.value)
            }
        }
        chunks.push(chunk)
        results = await pipeline.next()
    }
    return chunks
}
