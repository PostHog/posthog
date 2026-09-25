import { Message } from 'node-rdkafka'

import { FetchCandidatePool } from '../ingestion/pipelines/sessionreplay/ml-mirror-image-fetch/fetch-candidate-pool'
import { ImageFetchBatchJoiner } from '../ingestion/pipelines/sessionreplay/ml-mirror-image-fetch/image-fetch-batch-joiner'
import {
    buildImageFetchBatchHandlers,
    buildImageFetchConsumerConfigs,
    buildImageFetchConsumerOverrides,
    imageFetchBatchesPerPass,
    shutdownImageFetchConsumers,
} from './ingestion-session-replay-ml-image-fetch-server'
import { buildMlMirrorServerConfig } from './ingestion-session-replay-ml-mirror-server'

describe('image fetch consumer wiring', () => {
    it.each([
        ['the default', {}, 2, 2, 2, 102_400],
        ['four consumers', { SESSION_RECORDING_ML_IMAGE_FETCH_TARGET_PARTITIONS_PER_BATCH: 4 }, 4, 4, 2, 164_096],
        ['eight consumers', { SESSION_RECORDING_ML_IMAGE_FETCH_TARGET_PARTITIONS_PER_BATCH: 8 }, 8, 8, 2, 328_192],
        [
            'eight unjoined consumers',
            {
                SESSION_RECORDING_ML_IMAGE_FETCH_TARGET_PARTITIONS_PER_BATCH: 8,
                SESSION_RECORDING_ML_IMAGE_FETCH_JOIN_MEMBER_BATCHES: false,
            },
            8,
            1,
            2,
            328_192,
        ],
        [
            'eight continuous-pool consumers',
            {
                SESSION_RECORDING_ML_IMAGE_FETCH_TARGET_PARTITIONS_PER_BATCH: 8,
                SESSION_RECORDING_ML_IMAGE_FETCH_CONTINUOUS_POOL: true,
            },
            8,
            8,
            4,
            328_192,
        ],
        ['sixteen consumers', { SESSION_RECORDING_ML_IMAGE_FETCH_TARGET_PARTITIONS_PER_BATCH: 16 }, 16, 16, 2, 656_384],
    ])(
        'creates %s number of Kafka group members',
        (
            _name,
            overrides,
            expectedConsumers,
            expectedBatchesPerPass,
            expectedBatchesInFlightPerMember,
            expectedQueueBudget
        ) => {
            const serverConfig = buildMlMirrorServerConfig(overrides)
            const consumerConfigs = buildImageFetchConsumerConfigs(serverConfig)
            const consumerOverrides = buildImageFetchConsumerOverrides(serverConfig, consumerConfigs.length)

            expect(consumerConfigs).toHaveLength(expectedConsumers)
            expect(imageFetchBatchesPerPass(serverConfig, consumerConfigs.length)).toBe(expectedBatchesPerPass)
            expect(consumerConfigs.map((config) => config.maxBackgroundTasks)).toEqual(
                Array(expectedConsumers).fill(expectedBatchesInFlightPerMember)
            )
            expect(consumerConfigs.every((config) => config.backgroundTaskTimeoutMs === 240_000)).toBe(true)
            expect(consumerConfigs.map((config) => config.groupId)).toEqual(
                Array(expectedConsumers).fill(serverConfig.SESSION_RECORDING_ML_IMAGE_FETCH_GROUP_ID)
            )
            expect(Number(consumerOverrides['queued.max.messages.kbytes']) * expectedConsumers).toBeLessThanOrEqual(
                expectedQueueBudget
            )
            expect(Number(consumerOverrides['queued.max.messages.kbytes']) * expectedConsumers).toBeGreaterThanOrEqual(
                expectedQueueBudget - expectedConsumers
            )
            expect(Number(consumerOverrides['queued.max.messages.kbytes']) * 1024).toBeGreaterThanOrEqual(
                serverConfig.SESSION_RECORDING_ML_IMAGE_FETCH_MAX_IMAGE_BYTES * 2 + 64 * 1024
            )
        }
    )

    it.each([
        ['the joiner without a pool', false],
        ['its own pool window with a pool', true],
    ])('routes each member batch through %s', async (_name, withPool) => {
        const pool = withPool
            ? new FetchCandidatePool<unknown>(
                  { maxConcurrentPerRegistrableDomain: 6, refillRunnableUrls: 100, maxQueuedUrlsPerOwner: 1_000 },
                  { originCrawlDelayMs: () => 0, originNextImageStartAtMs: () => 0 }
              )
            : undefined
        const fetchConsumer = { handleBatch: jest.fn().mockResolvedValue(undefined) }
        const joiner = { handleBatch: jest.fn().mockResolvedValue(undefined) }
        const message: Message = { topic: 'test-topic', partition: 0, offset: 1, value: Buffer.from('x'), size: 1 }

        const handlers = buildImageFetchBatchHandlers(2, fetchConsumer, { candidatePool: pool }, joiner)
        await Promise.all(handlers.map((handler) => handler([message])))

        expect(handlers).toHaveLength(2)
        expect(joiner.handleBatch).toHaveBeenCalledTimes(withPool ? 0 : 2)
        expect(fetchConsumer.handleBatch).toHaveBeenCalledTimes(withPool ? 2 : 0)
        if (withPool) {
            const [firstAdmission, secondAdmission] = fetchConsumer.handleBatch.mock.calls.map((call) => call[2])
            expect(firstAdmission.owner).not.toBe(secondAdmission.owner)
        }
        pool?.close()
    })

    it.each([false, true])('waits for joined work before disconnecting and cleaning up (failure=%s)', async (fails) => {
        jest.useFakeTimers()
        try {
            const processBatch = jest.fn(
                (messages: Message[]) =>
                    new Promise<void>((resolve, reject) => {
                        setTimeout(
                            () => {
                                if (fails && messages[0].offset === 1) {
                                    reject(new Error('fetch failed'))
                                } else {
                                    resolve()
                                }
                            },
                            messages[0].offset === 1 ? 30_000 : 50_000
                        )
                    })
            )
            const joiner = new ImageFetchBatchJoiner(1, processBatch)
            const completions = await Promise.all(
                [1, 2].map((offset) =>
                    joiner.handleBatch([
                        { topic: 'test-topic', partition: 0, offset, value: Buffer.from('test'), size: 4 },
                    ])
                )
            )
            const work = Promise.allSettled(completions.map((batch) => batch?.backgroundTask ?? Promise.resolve()))
            const consumers = [0, 1].map(() => ({
                stopConsuming: jest.fn(() => new Promise<void>((resolve) => setTimeout(resolve, 20_000))),
                disconnect: jest.fn().mockResolvedValue(undefined),
            }))
            const cleanup = jest.fn()
            const shutdown = shutdownImageFetchConsumers(consumers, joiner).then(cleanup)

            expect(consumers.every((consumer) => consumer.stopConsuming.mock.calls.length === 1)).toBe(true)
            await jest.advanceTimersByTimeAsync(30_000)
            expect(consumers.every((consumer) => consumer.disconnect.mock.calls.length === 0)).toBe(true)
            expect(cleanup).not.toHaveBeenCalled()

            await jest.advanceTimersByTimeAsync(20_000)
            await shutdown
            await work
            expect(consumers.every((consumer) => consumer.disconnect.mock.calls.length === 1)).toBe(true)
            expect(cleanup).toHaveBeenCalledTimes(1)
        } finally {
            jest.useRealTimers()
        }
    })

    it.each([0, -1, 1.5, 17, Number.NaN, Number.MAX_SAFE_INTEGER + 1])(
        'refuses invalid target partition count %p',
        (targetPartitionsPerBatch) => {
            const serverConfig = buildMlMirrorServerConfig({
                SESSION_RECORDING_ML_IMAGE_FETCH_TARGET_PARTITIONS_PER_BATCH: targetPartitionsPerBatch,
            })

            expect(() => buildImageFetchConsumerConfigs(serverConfig)).toThrow(
                'image fetch batch target must be an integer between 1 and 16'
            )
        }
    )
})
