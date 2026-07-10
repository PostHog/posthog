import { captureException } from '~/common/utils/posthog'

import { ChunkProcessingStep } from './base-chunk-pipeline'
import { newChunkPipelineBuilder, newPipelineBuilder } from './builders'
import { createOkContext } from './helpers'
import { pipelineRetryAttemptsHistogram } from './metrics'
import { getRetryAttempts } from './metrics.test-utils'
import { PipelineResult, isDlqResult, isOkResult, ok } from './results'
import { withChunkRetry, withStepRetry } from './retry'
import { ProcessingStep } from './steps'

jest.setTimeout(1000)

jest.mock('~/common/utils/logger', () => ({
    logger: { debug: jest.fn(), info: jest.fn(), warn: jest.fn(), error: jest.fn() },
}))

jest.mock('~/common/utils/posthog', () => ({
    captureException: jest.fn(),
}))

const mockCaptureException = captureException as jest.MockedFunction<typeof captureException>

class RetriableError extends Error {
    isRetriable = true
}

class NonRetriableError extends Error {
    isRetriable = false
}

/**
 * A `run` executes a step wrapped with retry through the public builder interface
 * and returns the flat list of results, so `withStepRetry` (single item) and
 * `withChunkRetry` (batch) can share the same behavioral assertions.
 *
 * `script` runs once per attempt and may throw to simulate failures.
 */
interface Variant {
    label: string
    run(
        script: () => void,
        retry: Parameters<typeof withStepRetry>[1],
        opts?: { inputs?: number[]; stepName?: string }
    ): Promise<PipelineResult<string>[]>
}

const stepVariant: Variant = {
    label: 'withStepRetry (via pipe)',
    async run(script, retry, opts) {
        const inputs = opts?.inputs ?? [1]
        // Inline function literal so the computed-property key names the step (for the metric-name test).
        const step: ProcessingStep<number, string> = opts?.stepName
            ? {
                  [opts.stepName]: (v: number): Promise<PipelineResult<string>> => {
                      script()
                      return Promise.resolve(ok(String(v)))
                  },
              }[opts.stepName]
            : (v: number): Promise<PipelineResult<string>> => {
                  script()
                  return Promise.resolve(ok(String(v)))
              }
        const pipeline = newPipelineBuilder<number>().pipe(step, { retry }).build()
        const result = await pipeline.process(createOkContext(inputs[0], {}))
        return [result.result]
    },
}

const batchVariant: Variant = {
    label: 'withChunkRetry (via pipeChunk)',
    async run(script, retry, opts) {
        const inputs = opts?.inputs ?? [1]
        // Inline function literal so the computed-property key names the step (for the metric-name test).
        const step: ChunkProcessingStep<number, string> = opts?.stepName
            ? {
                  [opts.stepName]: (values: number[]): Promise<PipelineResult<string>[]> => {
                      script()
                      return Promise.resolve(values.map((v) => ok(String(v))))
                  },
              }[opts.stepName]
            : (values: number[]): Promise<PipelineResult<string>[]> => {
                  script()
                  return Promise.resolve(values.map((v) => ok(String(v))))
              }
        const pipeline = newChunkPipelineBuilder<number>().pipeChunk(step, { retry }).gather().build()
        pipeline.feed(inputs.map((v) => createOkContext(v, {})))
        const results = await pipeline.next()
        return (results ?? []).map((r) => r.result)
    },
}

describe('retry', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        pipelineRetryAttemptsHistogram.reset()
    })

    describe.each([stepVariant, batchVariant])('$label', (variant) => {
        it('retries retriable errors and eventually succeeds', async () => {
            let attempts = 0
            const script = (): void => {
                attempts++
                if (attempts < 3) {
                    throw new RetriableError('Temporary failure')
                }
            }

            const results = await variant.run(script, { name: 'retry_site', tries: 5, sleepMs: 1 })

            expect(attempts).toBe(3)
            expect(results.every(isOkResult)).toBe(true)
            expect(mockCaptureException).not.toHaveBeenCalled()
            expect(await getRetryAttempts('retry_site', 'completed')).toEqual({ count: 1, sum: 3 })
        })

        it('converts non-retriable errors to DLQ without retrying', async () => {
            const script = (): void => {
                throw new NonRetriableError('Validation failed')
            }

            const results = await variant.run(script, { name: 'retry_site', tries: 3, sleepMs: 1 })

            expect(results.length).toBeGreaterThanOrEqual(1)
            expect(results.every(isDlqResult)).toBe(true)
            expect(mockCaptureException).toHaveBeenCalledTimes(1)
            expect(await getRetryAttempts('retry_site', 'non_retriable')).toEqual({ count: 1, sum: 1 })
        })

        it('rethrows retriable errors after exhausting retries', async () => {
            const script = (): void => {
                throw new RetriableError('Always fails')
            }

            await expect(variant.run(script, { name: 'retry_site', tries: 2, sleepMs: 1 })).rejects.toThrow(
                'Always fails'
            )
            expect(await getRetryAttempts('retry_site', 'exhausted')).toEqual({ count: 1, sum: 2 })
        })

        it('rethrows errors without isRetriable after exhausting the default of 3 tries', async () => {
            const script = (): void => {
                throw new Error('No isRetriable property')
            }

            await expect(variant.run(script, { name: 'retry_site', sleepMs: 1 })).rejects.toThrow(
                'No isRetriable property'
            )
            expect(mockCaptureException).not.toHaveBeenCalled()
            expect(await getRetryAttempts('retry_site', 'exhausted')).toEqual({ count: 1, sum: 3 })
        })

        it('defaults the metric name to the step name', async () => {
            const results = await variant.run(() => {}, { sleepMs: 1 }, { stepName: 'geoipStep' })

            expect(results.every(isOkResult)).toBe(true)
            expect(await getRetryAttempts('geoipStep', 'completed')).toEqual({ count: 1, sum: 1 })
        })
    })

    it('maps a non-retriable batch error to one DLQ result per input value', async () => {
        const results = await batchVariant.run(
            () => {
                throw new NonRetriableError('Validation failed')
            },
            { name: 'retry_site', tries: 3, sleepMs: 1 },
            { inputs: [1, 2, 3] }
        )

        expect(results).toHaveLength(3)
        expect(results.every(isDlqResult)).toBe(true)
    })

    describe('preserves the wrapped step name', () => {
        const namedStep = function namedStep(): Promise<PipelineResult<string>> {
            return Promise.resolve(ok('x'))
        }
        const namedBatchStep = function namedBatchStep(values: number[]): Promise<PipelineResult<string>[]> {
            return Promise.resolve(values.map((v) => ok(String(v))))
        }

        it('for withStepRetry', () => {
            expect(withStepRetry(namedStep).name).toBe('namedStep')
        })

        it('for withChunkRetry', () => {
            expect(withChunkRetry(namedBatchStep).name).toBe('namedBatchStep')
        })
    })
})
