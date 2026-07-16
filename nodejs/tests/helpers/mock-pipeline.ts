import { Message } from 'node-rdkafka'

import { ChunkPipeline, ChunkPipelineResultWithContext } from '~/ingestion/framework/chunk-pipeline.interface'

/**
 * Creates a mock pipeline that returns pre-built results from next().
 *
 * Use this instead of feed() when test results contain redirect types,
 * since feed() only accepts R = never (no redirects in input).
 */
export function createMockPipeline<T, C extends { message: Message } = { message: Message }, R extends string = never>(
    results: ChunkPipelineResultWithContext<T, C, R>
): ChunkPipeline<T, T, C, C, R> {
    let returned = false
    return {
        feed: jest.fn(),
        next: jest.fn(() => {
            if (returned || results.length === 0) {
                return Promise.resolve(null)
            }
            returned = true
            return Promise.resolve(results)
        }),
    }
}
