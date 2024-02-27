import { randomUUID } from 'crypto'
import fs from 'fs/promises'
import { mkdirSync, rmSync } from 'node:fs'
import { TopicPartition, TopicPartitionOffset } from 'node-rdkafka'
import path from 'path'

import { waitForExpect } from '../../../../functional_tests/expectations'
import { defaultConfig } from '../../../../src/config/config'
import {
    SessionManagerBufferContext,
    SessionManagerContext,
} from '../../../../src/main/ingestion-queues/session-recording/services/session-manager-v3'
import { SessionRecordingIngesterV3 } from '../../../../src/main/ingestion-queues/session-recording/session-recordings-consumer-v3'
import { Hub, PluginsServerConfig, Team } from '../../../../src/types'
import { createHub } from '../../../../src/utils/db/hub'
import { getFirstTeam, resetTestDatabase } from '../../../helpers/sql'
import { createIncomingRecordingMessage, createKafkaMessage, createTP } from './fixtures'

const SESSION_RECORDING_REDIS_PREFIX = '@posthog-tests/replay/'

const tmpDir = path.join(__dirname, '../../../../.tmp/test_session_recordings')

const config: PluginsServerConfig = {
    ...defaultConfig,
    SESSION_RECORDING_PARTITION_REVOKE_OPTIMIZATION: true,
    SESSION_RECORDING_REDIS_PREFIX,
    SESSION_RECORDING_LOCAL_DIRECTORY: tmpDir,
}

async function deleteKeysWithPrefix(hub: Hub) {
    const redisClient = await hub.redisPool.acquire()
    const keys = await redisClient.keys(`${SESSION_RECORDING_REDIS_PREFIX}*`)
    const pipeline = redisClient.pipeline()
    keys.forEach(function (key) {
        pipeline.del(key)
    })
    await pipeline.exec()
    await hub.redisPool.release(redisClient)
}

const mockConsumer = {
    on: jest.fn(),
    commitSync: jest.fn(),
    commit: jest.fn(),
    queryWatermarkOffsets: jest.fn(),
    committed: jest.fn(),
    assignments: jest.fn(),
    isConnected: jest.fn(() => true),
    getMetadata: jest.fn(),
}

jest.mock('../../../../src/kafka/batch-consumer', () => {
    return {
        startBatchConsumer: jest.fn(() =>
            Promise.resolve({
                join: () => ({
                    finally: jest.fn(),
                }),
                stop: jest.fn(),
                consumer: mockConsumer,
            })
        ),
    }
})

jest.setTimeout(1000)

describe('ingester', () => {
    let ingester: SessionRecordingIngesterV3

    let hub: Hub
    let closeHub: () => Promise<void>
    let team: Team
    let teamToken = ''
    let mockOffsets: Record<number, number> = {}
    let mockCommittedOffsets: Record<number, number> = {}

    beforeAll(async () => {
        mkdirSync(path.join(config.SESSION_RECORDING_LOCAL_DIRECTORY, 'session-buffer-files'), { recursive: true })
        await resetTestDatabase()
    })

    beforeEach(async () => {
        if (await fs.stat(tmpDir).catch(() => null)) {
            await fs.rmdir(tmpDir, { recursive: true })
        }

        // The below mocks simulate committing to kafka and querying the offsets
        mockCommittedOffsets = {}
        mockOffsets = {}
        mockConsumer.commit.mockImplementation(
            (tpo: TopicPartitionOffset) => (mockCommittedOffsets[tpo.partition] = tpo.offset)
        )
        mockConsumer.queryWatermarkOffsets.mockImplementation((_topic, partition, _timeout, cb) => {
            cb(null, { highOffset: mockOffsets[partition] ?? 1, lowOffset: 0 })
        })

        mockConsumer.getMetadata.mockImplementation((options, cb) => {
            cb(null, {
                topics: [{ name: options.topic, partitions: [{ id: 0 }, { id: 1 }, { id: 2 }] }],
            })
        })

        mockConsumer.committed.mockImplementation((topicPartitions: TopicPartition[], _timeout, cb) => {
            const tpos: TopicPartitionOffset[] = topicPartitions.map((tp) => ({
                topic: tp.topic,
                partition: tp.partition,
                offset: mockCommittedOffsets[tp.partition] ?? 1,
            }))

            cb(null, tpos)
        })
        ;[hub, closeHub] = await createHub()
        team = await getFirstTeam(hub)
        teamToken = team.api_token
        await deleteKeysWithPrefix(hub)

        ingester = new SessionRecordingIngesterV3(config, hub.postgres, hub.objectStorage)
        await ingester.start()

        mockConsumer.assignments.mockImplementation(() => [createTP(0), createTP(1)])
    })

    afterEach(async () => {
        jest.setTimeout(10000)
        await deleteKeysWithPrefix(hub)
        await ingester.stop()
        await closeHub()
    })

    afterAll(() => {
        rmSync(config.SESSION_RECORDING_LOCAL_DIRECTORY, { recursive: true, force: true })
        jest.useRealTimers()
    })

    const createMessage = (session_id: string, partition = 1) => {
        mockOffsets[partition] = mockOffsets[partition] ?? 0
        mockOffsets[partition]++

        return createKafkaMessage(
            teamToken,
            {
                partition,
                offset: mockOffsets[partition],
            },
            {
                $session_id: session_id,
            }
        )
    }

    it('can parse debug partition config', () => {
        const config = {
            SESSION_RECORDING_DEBUG_PARTITION: '103',
            KAFKA_HOSTS: 'localhost:9092',
        } satisfies Partial<PluginsServerConfig> as PluginsServerConfig

        const ingester = new SessionRecordingIngesterV3(config, hub.postgres, hub.objectStorage)
        expect(ingester['debugPartition']).toEqual(103)
    })

    it('can parse absence of debug partition config', () => {
        const config = {
            KAFKA_HOSTS: 'localhost:9092',
        } satisfies Partial<PluginsServerConfig> as PluginsServerConfig

        const ingester = new SessionRecordingIngesterV3(config, hub.postgres, hub.objectStorage)
        expect(ingester['debugPartition']).toBeUndefined()
    })

    it('creates a new session manager if needed', async () => {
        const event = createIncomingRecordingMessage()
        await ingester.consume(event)
        await waitForExpect(() => {
            expect(Object.keys(ingester.sessions).length).toBe(1)
            expect(ingester.sessions['1__session_id_1']).toBeDefined()
        })
    })

    it('handles multiple incoming sessions', async () => {
        const event = createIncomingRecordingMessage()
        const event2 = createIncomingRecordingMessage({
            session_id: 'session_id_2',
        })
        await Promise.all([ingester.consume(event), ingester.consume(event2)])
        expect(Object.keys(ingester.sessions).length).toBe(2)
        expect(ingester.sessions['1__session_id_1']).toBeDefined()
        expect(ingester.sessions['1__session_id_2']).toBeDefined()
    })

    it('handles parallel ingestion of the same session', async () => {
        const event = createIncomingRecordingMessage()
        const event2 = createIncomingRecordingMessage()
        await Promise.all([ingester.consume(event), ingester.consume(event2)])
        expect(Object.keys(ingester.sessions).length).toBe(1)
        expect(ingester.sessions['1__session_id_1']).toBeDefined()
    })

    it('destroys a session manager if finished', async () => {
        const sessionId = `destroys-a-session-manager-if-finished-${randomUUID()}`
        const event = createIncomingRecordingMessage({
            session_id: sessionId,
        })
        await ingester.consume(event)
        expect(ingester.sessions[`1__${sessionId}`]).toBeDefined()
        ingester.sessions[`1__${sessionId}`].buffer!.context.createdAt = 0

        await ingester.flushAllReadySessions()

        await waitForExpect(() => {
            expect(ingester.sessions[`1__${sessionId}`]).not.toBeDefined()
        }, 10000)
    })

    describe('simulated rebalancing', () => {
        let otherIngester: SessionRecordingIngesterV3
        jest.setTimeout(5000) // Increased to cover lock delay

        beforeEach(async () => {
            otherIngester = new SessionRecordingIngesterV3(config, hub.postgres, hub.objectStorage)
            await otherIngester.start()
        })

        afterEach(async () => {
            await otherIngester.stop()
        })

        const getSessions = (
            ingester: SessionRecordingIngesterV3
        ): (SessionManagerContext & SessionManagerBufferContext)[] =>
            Object.values(ingester.sessions).map((x) => ({ ...x.context, ...x.buffer!.context }))

        /**
         * It is really hard to actually do rebalance tests against kafka, so we instead simulate the various methods and ensure the correct logic occurs
         * Simulates the rebalance and tests that the handled sessions are successfully dropped and picked up
         */
        it('rebalances new consumers', async () => {
            const partitionMsgs1 = [createMessage('session_id_1', 1), createMessage('session_id_2', 1)]
            const partitionMsgs2 = [createMessage('session_id_3', 2), createMessage('session_id_4', 2)]

            mockConsumer.assignments.mockImplementation(() => [createTP(1), createTP(2), createTP(3)])
            await ingester.handleEachBatch([...partitionMsgs1, ...partitionMsgs2])

            expect(getSessions(ingester)).toMatchObject([
                { sessionId: 'session_id_1', partition: 1, count: 1 },
                { sessionId: 'session_id_2', partition: 1, count: 1 },
                { sessionId: 'session_id_3', partition: 2, count: 1 },
                { sessionId: 'session_id_4', partition: 2, count: 1 },
            ])

            // Call handleEachBatch with both consumers - we simulate the assignments which
            // is what is responsible for the actual syncing of the sessions
            mockConsumer.assignments.mockImplementation(() => [createTP(2), createTP(3)])
            await otherIngester.handleEachBatch([createMessage('session_id_4', 2), createMessage('session_id_5', 2)])
            mockConsumer.assignments.mockImplementation(() => [createTP(1)])
            await ingester.handleEachBatch([createMessage('session_id_1', 1)])

            // Should still have the partition 1 sessions that didnt move with added events
            expect(getSessions(ingester)).toMatchObject([
                { sessionId: 'session_id_1', partition: 1, count: 2 },
                { sessionId: 'session_id_2', partition: 1, count: 1 },
            ])
            expect(getSessions(otherIngester)).toMatchObject([
                { sessionId: 'session_id_3', partition: 2, count: 1 },
                { sessionId: 'session_id_4', partition: 2, count: 2 },
                { sessionId: 'session_id_5', partition: 2, count: 1 },
            ])
        })
    })

    describe('stop()', () => {
        const setup = async (): Promise<void> => {
            const partitionMsgs1 = [createMessage('session_id_1', 1), createMessage('session_id_2', 1)]
            await ingester.handleEachBatch(partitionMsgs1)
        }

        // TODO: Unskip when we add back in the replay and console ingestion
        it('shuts down without error', async () => {
            await setup()

            await expect(ingester.stop()).resolves.toMatchObject([
                // destroy sessions,
                { status: 'fulfilled' },
                // // stop replay ingester
                // { status: 'fulfilled' },
                // // stop console ingester
                // { status: 'fulfilled' },
            ])
        })
    })

    describe('when a team is disabled', () => {
        it('ignores invalid teams', async () => {
            // non-zero offset because the code can't commit offset 0
            await ingester.handleEachBatch([
                createKafkaMessage('invalid_token', { offset: 12 }),
                createKafkaMessage('invalid_token', { offset: 13 }),
            ])

            expect(ingester.sessions).toEqual({})
        })
    })
})
