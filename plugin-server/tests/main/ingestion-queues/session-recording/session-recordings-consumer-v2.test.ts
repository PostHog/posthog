import { mkdirSync, rmSync } from 'node:fs'
import { Message } from 'node-rdkafka-acosom'
import path from 'path'

import { waitForExpect } from '../../../../functional_tests/expectations'
import { defaultConfig } from '../../../../src/config/config'
import { SessionRecordingIngesterV2 } from '../../../../src/main/ingestion-queues/session-recording/session-recordings-consumer-v2'
import { Hub, PluginsServerConfig } from '../../../../src/types'
import { createHub } from '../../../../src/utils/db/hub'
import { getFirstTeam, resetTestDatabase } from '../../../helpers/sql'
import { createIncomingRecordingMessage, createKafkaMessage, createTP } from './fixtures'

const SESSION_RECORDING_REDIS_PREFIX = '@posthog-tests/replay/'

const config: PluginsServerConfig = {
    ...defaultConfig,
    SESSION_RECORDING_PARTITION_REVOKE_OPTIMIZATION: true,
    SESSION_RECORDING_REDIS_PREFIX,
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

const mockCommit = jest.fn()
const mockQueryWatermarkOffsets = jest.fn((_1, _2, cb) => {
    cb(null, { highOffset: 0, lowOffset: 0 })
})

jest.mock('../../../../src/kafka/batch-consumer', () => {
    return {
        startBatchConsumer: jest.fn(() =>
            Promise.resolve({
                join: () => ({
                    finally: jest.fn(),
                }),
                stop: jest.fn(),
                consumer: {
                    on: jest.fn(),
                    commitSync: mockCommit,
                    commit: mockCommit,
                    queryWatermarkOffsets: mockQueryWatermarkOffsets,
                },
            })
        ),
    }
})

jest.setTimeout(1000)

describe('ingester', () => {
    let ingester: SessionRecordingIngesterV2

    let hub: Hub
    let closeHub: () => Promise<void>
    let teamToken = ''

    beforeAll(async () => {
        mkdirSync(path.join(config.SESSION_RECORDING_LOCAL_DIRECTORY, 'session-buffer-files'), { recursive: true })
        await resetTestDatabase()
    })

    beforeEach(async () => {
        ;[hub, closeHub] = await createHub()
        const team = await getFirstTeam(hub)
        teamToken = team.api_token
        await deleteKeysWithPrefix(hub)

        ingester = new SessionRecordingIngesterV2(config, hub.postgres, hub.objectStorage)
        await ingester.start()
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

    it('creates a new session manager if needed', async () => {
        const event = createIncomingRecordingMessage()
        await ingester.consume(event)
        await waitForExpect(() => {
            expect(Object.keys(ingester.sessions).length).toBe(1)
            expect(ingester.sessions['1-session_id_1']).toBeDefined()
        })
    })

    it('removes sessions on destroy', async () => {
        await ingester.consume(createIncomingRecordingMessage({ team_id: 2, session_id: 'session_id_1' }))
        await ingester.consume(createIncomingRecordingMessage({ team_id: 2, session_id: 'session_id_2' }))

        expect(Object.keys(ingester.sessions).length).toBe(2)
        expect(ingester.sessions['2-session_id_1']).toBeDefined()
        expect(ingester.sessions['2-session_id_2']).toBeDefined()

        await ingester.destroySessions([['2-session_id_1', ingester.sessions['2-session_id_1']]])

        expect(Object.keys(ingester.sessions).length).toBe(1)
        expect(ingester.sessions['2-session_id_2']).toBeDefined()
    })

    it('handles multiple incoming sessions', async () => {
        const event = createIncomingRecordingMessage()
        const event2 = createIncomingRecordingMessage({
            session_id: 'session_id_2',
        })
        await Promise.all([ingester.consume(event), ingester.consume(event2)])
        expect(Object.keys(ingester.sessions).length).toBe(2)
        expect(ingester.sessions['1-session_id_1']).toBeDefined()
        expect(ingester.sessions['1-session_id_2']).toBeDefined()
    })

    it('destroys a session manager if finished', async () => {
        const event = createIncomingRecordingMessage()
        await ingester.consume(event)
        expect(ingester.sessions['1-session_id_1']).toBeDefined()
        // Force the flush
        ingester.partitionAssignments[event.metadata.partition] = {
            lastMessageTimestamp: Date.now() + defaultConfig.SESSION_RECORDING_MAX_BUFFER_AGE_SECONDS,
        }

        await ingester.flushAllReadySessions()

        expect(ingester.sessions['1-session_id_1']).not.toBeDefined()
    })

    describe('parsing the message', () => {
        it('can handle numeric distinct_ids', async () => {
            const numeric_id = 12345

            const parsedMessage = await ingester.parseKafkaMessage(
                {
                    value: Buffer.from(
                        JSON.stringify({
                            uuid: '018a47df-a0f6-7761-8635-439a0aa873bb',
                            distinct_id: String(numeric_id),
                            ip: '127.0.0.1',
                            site_url: 'http://127.0.0.1:8000',
                            data: JSON.stringify({
                                uuid: '018a47df-a0f6-7761-8635-439a0aa873bb',
                                event: '$snapshot_items',
                                properties: {
                                    distinct_id: numeric_id,
                                    $session_id: '018a47c2-2f4a-70a8-b480-5e51d8b8d070',
                                    $window_id: '018a47c2-2f4a-70a8-b480-5e52f5480448',
                                    $snapshot_items: [
                                        {
                                            type: 6,
                                            data: {
                                                plugin: 'rrweb/console@1',
                                                payload: {
                                                    level: 'log',
                                                    trace: [
                                                        'HedgehogActor.setAnimation (http://127.0.0.1:8000/static/toolbar.js?_ts=1693421010000:105543:17)',
                                                        'HedgehogActor.setRandomAnimation (http://127.0.0.1:8000/static/toolbar.js?_ts=1693421010000:105550:14)',
                                                        'HedgehogActor.update (http://127.0.0.1:8000/static/toolbar.js?_ts=1693421010000:105572:16)',
                                                        'loop (http://127.0.0.1:8000/static/toolbar.js?_ts=1693421010000:105754:15)',
                                                    ],
                                                    payload: ['"Hedgehog: Will \'jump\' for 2916.6666666666665ms"'],
                                                },
                                            },
                                            timestamp: 1693422950693,
                                        },
                                    ],
                                    $snapshot_consumer: 'v2',
                                },
                                offset: 2187,
                            }),
                            now: '2023-08-30T19:15:54.887316+00:00',
                            sent_at: '2023-08-30T19:15:54.882000+00:00',
                            token: 'the_token',
                        })
                    ),
                    timestamp: 1,
                    size: 1,
                    topic: 'the_topic',
                    offset: 1,
                    partition: 1,
                } satisfies Message,
                () => Promise.resolve(1)
            )
            expect(parsedMessage).toEqual({
                distinct_id: '12345',
                events: expect.any(Array),
                metadata: {
                    offset: 1,
                    partition: 1,
                    timestamp: 1,
                    topic: 'the_topic',
                },
                session_id: '018a47c2-2f4a-70a8-b480-5e51d8b8d070',
                team_id: 1,
                window_id: '018a47c2-2f4a-70a8-b480-5e52f5480448',
            })
        })
    })

    // NOTE: Committing happens by the parent
    describe('offset committing', () => {
        const metadata = {
            partition: 1,
            topic: 'session_recording_events',
        }
        let _offset = 0
        const offset = () => _offset++

        const addMessage = (session_id: string) =>
            createIncomingRecordingMessage({ session_id }, { ...metadata, offset: offset() })

        beforeEach(() => {
            _offset = 0
        })

        const tryToCommitLatestOffset = async () => {
            await ingester.commitOffset(metadata.topic, metadata.partition, _offset)
        }

        it('should commit offsets in simple cases', async () => {
            await ingester.consume(addMessage('sid1'))
            await ingester.consume(addMessage('sid1'))
            expect(_offset).toBe(2)
            await tryToCommitLatestOffset()
            // Doesn't flush if we have a blocking session
            expect(mockCommit).toHaveBeenCalledTimes(0)
            await ingester.sessions['1-sid1']?.flush('buffer_age')
            await tryToCommitLatestOffset()

            expect(mockCommit).toHaveBeenCalledTimes(1)
            expect(mockCommit).toHaveBeenLastCalledWith({
                ...metadata,
                offset: 3,
            })
        })

        it('should commit higher values but not lower', async () => {
            // We need to simulate the paritition assignent logic here
            ingester.partitionAssignments[1] = {}
            await ingester.consume(addMessage('sid1'))
            await ingester.sessions['1-sid1']?.flush('buffer_age')
            await tryToCommitLatestOffset()

            expect(mockCommit).toHaveBeenCalledTimes(1)
            expect(mockCommit).toHaveBeenLastCalledWith({
                ...metadata,
                offset: 2,
            })

            const olderOffsetSomehow = addMessage('sid1')
            olderOffsetSomehow.metadata.offset = 1

            await ingester.consume(olderOffsetSomehow)
            await ingester.sessions['1-sid1']?.flush('buffer_age')
            await ingester.commitOffset(metadata.topic, metadata.partition, 1)
            expect(mockCommit).toHaveBeenCalledTimes(1)

            await ingester.consume(addMessage('sid1'))
            await ingester.sessions['1-sid1']?.flush('buffer_age')
            await tryToCommitLatestOffset()

            expect(mockCommit).toHaveBeenCalledTimes(2)
            expect(mockCommit).toHaveBeenLastCalledWith({
                ...metadata,
                offset: 4,
            })
        })

        it('should commit the lowest known offset if there is a blocking session', async () => {
            await ingester.consume(addMessage('sid1')) // 1
            await ingester.consume(addMessage('sid2')) // 2
            await ingester.consume(addMessage('sid2')) // 3
            await ingester.consume(addMessage('sid2')) // 4
            await ingester.sessions['1-sid2']?.flush('buffer_age')
            await tryToCommitLatestOffset()

            // No offsets are below the blocking one
            expect(mockCommit).not.toHaveBeenCalled()
            await ingester.sessions['1-sid1']?.flush('buffer_age')

            // Simulating the next incoming message triggers a commit for sure
            await tryToCommitLatestOffset()
            expect(mockCommit).toHaveBeenLastCalledWith({
                ...metadata,
                offset: 5,
            })
        })

        it('should commit one lower than the blocking session if that is the highest', async () => {
            await ingester.consume(addMessage('sid1')) // 1
            await ingester.consume(addMessage('sid2')) // 2
            await ingester.consume(addMessage('sid2')) // 3
            await ingester.consume(addMessage('sid2')) // 4
            await ingester.sessions['1-sid2']?.flush('buffer_age')
            await tryToCommitLatestOffset()

            // No offsets are below the blocking one
            expect(mockCommit).not.toHaveBeenCalled()
            await ingester.consume(addMessage('sid2')) // 5
            await ingester.sessions['1-sid1']?.flush('buffer_age')
            await tryToCommitLatestOffset()

            expect(mockCommit).toHaveBeenLastCalledWith({
                ...metadata,
                offset: 5, // Same as the blocking session and more than the highest commitable for sid1 (1)
            })
        })

        it('should not be affected by other partitions ', async () => {
            createIncomingRecordingMessage({ session_id: 'sid1' }, { ...metadata, partition: 2, offset: offset() })
            await ingester.consume(addMessage('sid2')) // 2
            await ingester.consume(addMessage('sid2')) // 3
            await ingester.sessions['1-sid2']?.flush('buffer_age')
            await tryToCommitLatestOffset()

            expect(mockCommit).toHaveBeenLastCalledWith({
                ...metadata,
                offset: 4,
            })
        })
    })

    describe('simulated rebalancing', () => {
        let otherIngester: SessionRecordingIngesterV2
        jest.setTimeout(5000) // Increased to cover lock delay

        beforeEach(async () => {
            otherIngester = new SessionRecordingIngesterV2(config, hub.postgres, hub.objectStorage)
            await otherIngester.start()
        })

        afterEach(async () => {
            await otherIngester.stop()
        })
        /**
         * It is really hard to actually do rebalance tests against kafka, so we instead simulate the various methods and ensure the correct logic occurs
         */
        it('rebalances new consumers', async () => {
            const partitionMsgs1 = [
                createKafkaMessage(
                    teamToken,
                    {
                        partition: 1,
                        offset: 1,
                    },
                    {
                        $session_id: 'session_id_1',
                    }
                ),

                createKafkaMessage(
                    teamToken,
                    {
                        partition: 1,
                        offset: 2,
                    },
                    {
                        $session_id: 'session_id_2',
                    }
                ),
            ]

            const partitionMsgs2 = [
                createKafkaMessage(
                    teamToken,
                    {
                        partition: 2,
                        offset: 1,
                    },
                    {
                        $session_id: 'session_id_3',
                    }
                ),
                createKafkaMessage(
                    teamToken,
                    {
                        partition: 2,
                        offset: 2,
                    },
                    {
                        $session_id: 'session_id_4',
                    }
                ),
            ]

            await ingester.onAssignPartitions([createTP(1), createTP(2), createTP(3)])
            await ingester.handleEachBatch([...partitionMsgs1, ...partitionMsgs2])

            expect(
                Object.values(ingester.sessions).map((x) => `${x.partition}:${x.sessionId}:${x.buffer.count}`)
            ).toEqual(['1:session_id_1:1', '1:session_id_2:1', '2:session_id_3:1', '2:session_id_4:1'])

            const rebalancePromises = [
                ingester.onRevokePartitions([createTP(2), createTP(3)]),
                otherIngester.onAssignPartitions([createTP(2), createTP(3)]),
            ]

            // Should immediately be removed from the tracked sessions
            expect(
                Object.values(ingester.sessions).map((x) => `${x.partition}:${x.sessionId}:${x.buffer.count}`)
            ).toEqual(['1:session_id_1:1', '1:session_id_2:1'])

            // Call the second ingester to receive the messages. The revocation should still be in progress meaning they are "paused" for a bit
            // Once the revocation is complete the second ingester should receive the messages but drop most of them as they got flushes by the revoke
            await otherIngester.handleEachBatch([
                ...partitionMsgs2,
                createKafkaMessage(
                    teamToken,
                    {
                        partition: 2,
                        offset: 3,
                    },
                    {
                        $session_id: 'session_id_4',
                    }
                ),
            ])

            await Promise.all(rebalancePromises)

            // Should still have the partition 1 sessions that didnt move
            expect(
                Object.values(ingester.sessions).map((x) => `${x.partition}:${x.sessionId}:${x.buffer.count}`)
            ).toEqual(['1:session_id_1:1', '1:session_id_2:1'])

            // Should have session_id_4 but not session_id_3 as it was flushed
            expect(
                Object.values(otherIngester.sessions).map((x) => `${x.partition}:${x.sessionId}:${x.buffer.count}`)
            ).toEqual(['2:session_id_4:1'])
        })
    })

    describe('stop()', () => {
        const setup = async (): Promise<void> => {
            const partitionMsgs1 = [
                createKafkaMessage(
                    teamToken,
                    {
                        partition: 1,
                        offset: 1,
                    },
                    {
                        $session_id: 'session_id_1',
                    }
                ),

                createKafkaMessage(
                    teamToken,
                    {
                        partition: 1,
                        offset: 2,
                    },
                    {
                        $session_id: 'session_id_2',
                    }
                ),
            ]

            await ingester.onAssignPartitions([createTP(1)])
            await ingester.handleEachBatch(partitionMsgs1)
        }

        // NOTE: This test is a sanity check for the follow up test. It demonstrates what happens if we shutdown in the wrong order
        // It doesn't reliably work though as the onRevoke is called via the kafka lib ending up with dangling promises so rather it is here as a reminder
        // demonstation for when we need it
        it.skip('shuts down with error if redis forcefully shutdown', async () => {
            await setup()

            await ingester.redisPool.drain()
            await ingester.redisPool.clear()

            // revoke, realtime unsub, replay stop
            await expect(ingester.stop()).resolves.toMatchObject([
                { status: 'rejected' },
                { status: 'fulfilled' },
                { status: 'fulfilled' },
            ])
        })
        it('shuts down without error', async () => {
            await setup()

            // revoke, realtime unsub, replay stop
            await expect(ingester.stop()).resolves.toMatchObject([
                { status: 'fulfilled' },
                { status: 'fulfilled' },
                { status: 'fulfilled' },
            ])
        })
    })
})
