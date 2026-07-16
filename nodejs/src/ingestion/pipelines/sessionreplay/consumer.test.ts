import { Message } from 'node-rdkafka'

import { ingestionLagGauge, ingestionLagHistogram } from '~/common/metrics'
import { PostgresRouter } from '~/common/utils/db/postgres'
import { SessionReplayPipeline, runSessionReplayPipeline } from '~/ingestion/pipelines/sessionreplay'
import { KeyStore, RecordingEncryptor } from '~/ingestion/pipelines/sessionreplay/shared/types'
import { RedisPool } from '~/types'

import { getDefaultSessionRecordingApiConfig, getDefaultSessionRecordingConfig } from './config'
import { SessionRecordingIngester, SessionRecordingIngesterConfig } from './consumer'
import { BlackholeSessionBatchFileStorage } from './sessions/blackhole-session-batch-writer'

jest.mock('~/common/kafka/consumer/consumer-v2', () => {
    class FakeKafkaConsumerV2 {
        public connect = jest.fn().mockResolvedValue(undefined)
        public stopConsuming = jest.fn().mockResolvedValue(undefined)
        public disconnect = jest.fn().mockResolvedValue(undefined)
        public offsetsStore = jest.fn()
        public assignments = jest.fn().mockReturnValue([])
        public isHealthy = jest.fn()
    }
    return { KafkaConsumerV2: FakeKafkaConsumerV2 }
})

jest.mock('~/ingestion/pipelines/sessionreplay', () => ({
    ...jest.requireActual('~/ingestion/pipelines/sessionreplay'),
    runSessionReplayPipeline: jest.fn(),
}))

function deferred(): { promise: Promise<void>; resolve: () => void } {
    let resolve!: () => void
    const promise = new Promise<void>((r) => (resolve = r))
    return { promise, resolve }
}

/** Flush all pending microtasks (one macrotask hop). */
function flushMicrotasks(): Promise<void> {
    return new Promise((resolve) => setImmediate(resolve))
}

function kafkaMessage(partition: number, offset: number, capturedAtMs?: number): Message {
    return {
        value: Buffer.from('data'),
        size: 4,
        topic: 'test-session-replay-topic',
        partition,
        offset,
        timestamp: Date.now(),
        headers: capturedAtMs === undefined ? undefined : [{ now: Buffer.from(new Date(capturedAtMs).toISOString()) }],
    }
}

async function lagHistogramCount(partition: string): Promise<number | undefined> {
    const metric = await ingestionLagHistogram.get()
    return metric.values.find(
        (v) => v.metricName === 'ingestion_lag_ms_histogram_count' && v.labels.partition === partition
    )?.value
}

describe('SessionRecordingIngester', () => {
    let ingester: SessionRecordingIngester
    let events: string[]

    const runPipelineMock = jest.mocked(runSessionReplayPipeline)

    const consumeTopic = getDefaultSessionRecordingConfig().INGESTION_SESSION_REPLAY_CONSUMER_CONSUME_TOPIC

    const createIngester = (configOverrides: Partial<SessionRecordingIngesterConfig> = {}): void => {
        const config: SessionRecordingIngesterConfig = {
            ...getDefaultSessionRecordingConfig(),
            ...getDefaultSessionRecordingApiConfig(),
            INGESTION_OVERFLOW_MODE: 'disabled',
            INGESTION_PIPELINE: 'sessionreplay',
            INGESTION_LANE: 'main',
            // Age/size flushes would interleave with the flush under test; keep them out of
            // reach unless a test opts in via overrides.
            SESSION_RECORDING_MAX_BATCH_AGE_MS: 60 * 60 * 1000,
            SESSION_RECORDING_MAX_BATCH_SIZE_KB: 1024 * 1024,
            ...configOverrides,
        }

        const fakeKeyStore = {
            start: jest.fn().mockResolvedValue(undefined),
            stop: jest.fn(),
        } as unknown as KeyStore
        const fakeEncryptor = {
            start: jest.fn().mockResolvedValue(undefined),
        } as unknown as RecordingEncryptor

        ingester = new SessionRecordingIngester(
            config,
            {} as jest.Mocked<PostgresRouter>,
            {} as unknown as ConstructorParameters<typeof SessionRecordingIngester>[2],
            {} as unknown as RedisPool,
            {} as unknown as RedisPool,
            {
                fileStorage: new BlackholeSessionBatchFileStorage(),
                keyStore: fakeKeyStore,
                encryptor: fakeEncryptor,
                createPipeline: () => ({}) as unknown as SessionReplayPipeline,
            }
        )

        jest.mocked(ingester.kafkaConsumer).offsetsStore.mockImplementation(() => {
            events.push('offsets_stored')
        })
        jest.mocked(ingester.kafkaConsumer).disconnect.mockImplementation(() => {
            events.push('disconnected')
            return Promise.resolve()
        })
    }

    beforeEach(() => {
        events = []
        runPipelineMock.mockReset()
        createIngester()
    })

    it('stop() stores the in-flight batch offsets only after its side effects settle, before disconnect', async () => {
        const pipelineEntered = deferred()
        const pipelineGate = deferred()

        // Models a poll batch mid-record when stop() arrives: the pipeline holds the batch lock
        // until the gate opens, and only then schedules its side effect (a DLQ/overflow produce
        // that takes one macrotask to become durable) and reports its offsets.
        runPipelineMock.mockImplementation(async (_pipeline, _messages, _recorder, scheduler) => {
            pipelineEntered.resolve()
            await pipelineGate.promise
            void scheduler.schedule(
                new Promise<void>((resolve) =>
                    setImmediate(() => {
                        events.push('side_effect_settled')
                        resolve()
                    })
                )
            )
            return new Map([[0, 42]])
        })

        const batchPromise = ingester.handleEachBatch([kafkaMessage(0, 42)])
        await pipelineEntered.promise

        // Model the real consumer contract: stopConsuming resolves only once the in-flight
        // eachBatch has settled. (The drain itself is covered by the consumer-v2 tests.)
        jest.mocked(ingester.kafkaConsumer).stopConsuming.mockImplementation(async () => {
            await batchPromise
        })

        const stopPromise = ingester.stop()
        await flushMicrotasks()

        // The batch finishes: it schedules its side effect and reports offset 42 for partition 0.
        pipelineGate.resolve()

        await batchPromise
        await stopPromise

        // The shutdown contract: the batch's produce must be durable before its offset is stored,
        // and the offset must be stored before disconnect commits it to the broker.
        expect(events).toEqual(['side_effect_settled', 'offsets_stored', 'disconnected'])
    })

    it('flushes on the age trigger: side effects drain before the batch offsets are stored, at exactly highest+1', async () => {
        createIngester({ SESSION_RECORDING_MAX_BATCH_AGE_MS: 0 })

        // The pipeline schedules a side effect (a DLQ/overflow produce that takes one macrotask
        // to become durable) and reports its offsets; the age trigger then flushes immediately.
        runPipelineMock.mockImplementation((_pipeline, _messages, _recorder, scheduler) => {
            void scheduler.schedule(
                new Promise<void>((resolve) =>
                    setImmediate(() => {
                        events.push('side_effect_settled')
                        resolve()
                    })
                )
            )
            return Promise.resolve(new Map([[0, 42]]))
        })

        await ingester.handleEachBatch([kafkaMessage(0, 42)])

        // Never commit a message's offset before its produce is durable — and commit at
        // exactly the next-to-process offset.
        expect(events).toEqual(['side_effect_settled', 'offsets_stored'])
        expect(jest.mocked(ingester.kafkaConsumer).offsetsStore).toHaveBeenCalledWith([
            { topic: consumeTopic, partition: 0, offset: 43 },
        ])
    })

    it('reports ingestion lag only once the batch is flushed', async () => {
        ingestionLagGauge.reset()
        ingestionLagHistogram.reset()

        // The default ingester keeps age/size out of reach, so recording a batch does not flush it —
        // and lag must not be observed until the data is durably ingested.
        runPipelineMock.mockResolvedValue(new Map([[0, 42]]))
        await ingester.handleEachBatch([kafkaMessage(0, 42, Date.now() - 5000)])
        expect(await lagHistogramCount('0')).toBeUndefined()

        // With the age trigger the batch flushes immediately, so its capture lag is observed post-flush.
        createIngester({ SESSION_RECORDING_MAX_BATCH_AGE_MS: 0 })
        runPipelineMock.mockResolvedValue(new Map([[0, 43]]))
        await ingester.handleEachBatch([kafkaMessage(0, 43, Date.now() - 5000)])
        expect(await lagHistogramCount('0')).toBe(1)
    })

    it('retains pending lag samples when a flush fails, reporting them on the next successful flush', async () => {
        ingestionLagHistogram.reset()
        createIngester({ SESSION_RECORDING_MAX_BATCH_AGE_MS: 0 })

        // The first flush fails at the offset-store step, after the batch's capture timestamp was buffered.
        jest.mocked(ingester.kafkaConsumer).offsetsStore.mockImplementationOnce(() => {
            throw new Error('offset store failed')
        })
        runPipelineMock.mockResolvedValue(new Map([[0, 42]]))
        await expect(ingester.handleEachBatch([kafkaMessage(0, 42, Date.now() - 5000)])).rejects.toThrow(
            'offset store failed'
        )
        // The flush threw, so nothing is observed and the sample stays pending for the next flush.
        expect(await lagHistogramCount('0')).toBeUndefined()

        // The next batch flushes cleanly and reports both the retained and the new sample.
        runPipelineMock.mockResolvedValue(new Map([[0, 43]]))
        await ingester.handleEachBatch([kafkaMessage(0, 43, Date.now() - 5000)])
        expect(await lagHistogramCount('0')).toBe(2)
    })

    it('start() wires the revoke hook, and the hook flushes the tracked offsets', async () => {
        await ingester.start()
        const connectMock = jest.mocked(ingester.kafkaConsumer).connect
        expect(connectMock).toHaveBeenCalledTimes(1)
        const [eachBatch, onPartitionsRevoked] = connectMock.mock.calls[0]
        expect(onPartitionsRevoked).toBeDefined()

        runPipelineMock.mockImplementation(() => Promise.resolve(new Map([[0, 7]])))
        await eachBatch([kafkaMessage(0, 7)])
        // Age/size are out of reach, so nothing has flushed yet.
        expect(events).toEqual([])

        await onPartitionsRevoked!([{ topic: consumeTopic, partition: 0 }])
        expect(jest.mocked(ingester.kafkaConsumer).offsetsStore).toHaveBeenCalledWith([
            { topic: consumeTopic, partition: 0, offset: 8 },
        ])

        await ingester.stop()
    })
})
