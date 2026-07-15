import { Message } from 'node-rdkafka'

import { PostgresRouter } from '~/common/utils/db/postgres'
import { runSessionReplayPipeline } from '~/ingestion/pipelines/sessionreplay'
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

function kafkaMessage(partition: number, offset: number): Message {
    return {
        value: Buffer.from('data'),
        size: 4,
        topic: 'test-session-replay-topic',
        partition,
        offset,
        timestamp: Date.now(),
    }
}

describe('SessionRecordingIngester', () => {
    let ingester: SessionRecordingIngester
    let events: string[]

    const runPipelineMock = jest.mocked(runSessionReplayPipeline)

    beforeEach(() => {
        events = []
        runPipelineMock.mockReset()

        const config: SessionRecordingIngesterConfig = {
            ...getDefaultSessionRecordingConfig(),
            ...getDefaultSessionRecordingApiConfig(),
            INGESTION_OVERFLOW_MODE: 'disabled',
            INGESTION_PIPELINE: 'sessionreplay',
            INGESTION_LANE: 'main',
            // Age/size flushes would interleave with the stop() flush under test; keep them out of reach.
            SESSION_RECORDING_MAX_BATCH_AGE_MS: 60 * 60 * 1000,
            SESSION_RECORDING_MAX_BATCH_SIZE_KB: 1024 * 1024,
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
            }
        )

        jest.mocked(ingester.kafkaConsumer).offsetsStore.mockImplementation(() => {
            events.push('offsets_stored')
        })
        jest.mocked(ingester.kafkaConsumer).disconnect.mockImplementation(() => {
            events.push('disconnected')
            return Promise.resolve()
        })
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
})
