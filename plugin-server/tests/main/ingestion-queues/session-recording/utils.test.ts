import { Settings } from 'luxon'
import { Message, MessageHeader } from 'node-rdkafka'

import { KafkaProducerWrapper } from '../../../../src/kafka/producer'
import {
    allSettledWithConcurrency,
    getLagMultiplier,
    maxDefined,
    minDefined,
    parseKafkaBatch,
    parseKafkaMessage,
} from '../../../../src/main/ingestion-queues/session-recording/utils'
import { UUIDT } from '../../../../src/utils/utils'

describe('session-recording utils', () => {
    const validMessage = (distinctId: number | string, headers?: MessageHeader[], value?: Record<string, any>) =>
        ({
            headers: headers || [{ token: 'the_token' }],
            value: Buffer.from(
                JSON.stringify({
                    uuid: '018a47df-a0f6-7761-8635-439a0aa873bb',
                    distinct_id: String(distinctId),
                    ip: '127.0.0.1',
                    site_url: 'http://127.0.0.1:8000',
                    data: JSON.stringify({
                        uuid: '018a47df-a0f6-7761-8635-439a0aa873bb',
                        event: '$snapshot_items',
                        properties: {
                            distinct_id: distinctId,
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
                    ...value,
                })
            ),
            timestamp: 1,
            size: 42,
            topic: 'the_topic',
            offset: 1,
            partition: 1,
        }) satisfies Message

    describe('parseKafkaMessage', () => {
        let fakeProducer: KafkaProducerWrapper
        beforeEach(() => {
            Settings.now = () => new Date('2023-08-30T19:15:54.887316+00:00').getTime()
            fakeProducer = { queueMessages: jest.fn(() => Promise.resolve()) } as unknown as KafkaProducerWrapper
        })

        it('can parse a message correctly', async () => {
            const parsedMessage = await parseKafkaMessage(
                validMessage('my-distinct-id', [{ token: 'something' }]),
                () => Promise.resolve({ teamId: 1, consoleLogIngestionEnabled: false }),
                fakeProducer
            )
            expect(parsedMessage).toMatchSnapshot()
        })
        it('can handle numeric distinct_ids', async () => {
            const numericId = 12345
            const parsedMessage = await parseKafkaMessage(
                validMessage(numericId, [{ token: 'something' }]),
                () => Promise.resolve({ teamId: 1, consoleLogIngestionEnabled: false }),
                fakeProducer
            )
            expect(parsedMessage).toMatchObject({
                distinct_id: String(numericId),
                eventsByWindowId: expect.any(Object),
                metadata: {
                    consoleLogIngestionEnabled: false,
                },
                session_id: '018a47c2-2f4a-70a8-b480-5e51d8b8d070',
                team_id: 1,
            })
        })

        it('filters out invalid rrweb events', async () => {
            const numeric_id = 12345

            const createMessage = ($snapshot_items: unknown[]) => {
                return {
                    headers: [{ token: Buffer.from('the_token') }],
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
                                    $snapshot_items: $snapshot_items,
                                },
                            }),
                            token: 'the_token',
                        })
                    ),
                    timestamp: 1,
                    size: 1,
                    topic: 'the_topic',
                    offset: 1,
                    partition: 1,
                } satisfies Message
            }

            const parsedMessage = await parseKafkaMessage(
                createMessage([
                    {
                        type: 6,
                        data: {},
                        timestamp: null,
                    },
                ]),
                () => Promise.resolve({ teamId: 1, consoleLogIngestionEnabled: true }),
                fakeProducer
            )
            expect(parsedMessage).toEqual(undefined)

            const parsedMessage2 = await parseKafkaMessage(
                createMessage([
                    {
                        type: 6,
                        data: {},
                        timestamp: null,
                    },
                    {
                        type: 6,
                        data: {},
                        timestamp: 123,
                    },
                ]),
                () => Promise.resolve({ teamId: 1, consoleLogIngestionEnabled: true }),
                fakeProducer
            )
            expect(parsedMessage2).toMatchObject({
                eventsByWindowId: {
                    '018a47c2-2f4a-70a8-b480-5e52f5480448': [
                        {
                            data: {},
                            timestamp: 123,
                            type: 6,
                        },
                    ],
                },
            })

            const parsedMessage3 = await parseKafkaMessage(
                createMessage([null]),
                () => Promise.resolve({ teamId: 1, consoleLogIngestionEnabled: false }),
                fakeProducer
            )
            expect(parsedMessage3).toEqual(undefined)
        })

        function expectedIngestionWarningMessage(details: Record<string, any>): Record<string, any> {
            return {
                value: JSON.stringify({
                    team_id: 1,
                    type: 'replay_lib_version_too_old',
                    source: 'plugin-server',
                    details: JSON.stringify(details),
                    timestamp: '2023-08-30 19:15:54.887',
                }),
            }
        }

        test.each([
            ['absent lib version means no call to capture ingestion warning', [], []],
            ['unknown lib version means no call to capture ingestion warning', [{ lib_version: 'unknown' }], []],
            ['not-three-part lib version means no call to capture ingestion warning', [{ lib_version: '1.25' }], []],
            [
                'three-part non-numeric lib version means no call to capture ingestion warning',
                [{ lib_version: '1.twenty.2' }],
                [],
            ],
            [
                'three-part lib version that is recent enough means no call to capture ingestion warning',
                [{ lib_version: '1.116.0' }],
                [],
            ],
            [
                'three-part lib version that is too old means call to capture ingestion warning',
                [{ lib_version: '1.74.0' }],
                [
                    [
                        {
                            messages: [
                                expectedIngestionWarningMessage({
                                    libVersion: '1.74.0',
                                    parsedVersion: { major: 1, minor: 74 },
                                }),
                            ],
                            topic: 'clickhouse_ingestion_warnings_test',
                        },
                    ],
                ],
            ],
            [
                'another three-part lib version that is too old means call to capture ingestion warning',
                [{ lib_version: '1.32.0' }],
                [
                    [
                        {
                            messages: [
                                expectedIngestionWarningMessage({
                                    libVersion: '1.32.0',
                                    parsedVersion: { major: 1, minor: 32 },
                                }),
                            ],
                            topic: 'clickhouse_ingestion_warnings_test',
                        },
                    ],
                ],
            ],
        ])('lib_version - captureIngestionWarning - %s', async (_name, headers, expectedCalls) => {
            await parseKafkaMessage(
                validMessage(12345, [{ token: 'q123' } as MessageHeader].concat(headers), {
                    $snapshot_consumer: 'v2',
                }),
                () => Promise.resolve({ teamId: 1, consoleLogIngestionEnabled: false }),
                fakeProducer
            )
            expect(jest.mocked(fakeProducer.queueMessages).mock.calls).toEqual(expectedCalls)
        })

        describe('team token must be in header *not* body', () => {
            const mockTeamResolver = jest.fn()

            beforeEach(() => {
                mockTeamResolver.mockReset()
                mockTeamResolver.mockResolvedValue({ teamId: 1, consoleLogIngestionEnabled: false })
            })

            test.each([
                [
                    'calls the team id resolver once when token is in header, even if not in the body',
                    'the_token',
                    undefined,
                    ['the_token'],
                ],
                [
                    'calls the team id resolver once when token is in header, even if it is in the body',
                    'the_token',
                    'the body token',
                    ['the_token'],
                ],
                [
                    'does not call the team id resolver when token is not in header, and not in body',
                    undefined,
                    undefined,
                    undefined,
                ],
                [
                    'does not call the team id resolver when token is not in header, but is in body',
                    undefined,
                    'the body token',
                    undefined,
                ],
            ])('%s', async (_name, headerToken, payloadToken, expectedCalls) => {
                await parseKafkaMessage(
                    validMessage(12345, headerToken ? [{ token: Buffer.from(headerToken) }] : [], {
                        token: payloadToken,
                    }),
                    mockTeamResolver,
                    fakeProducer
                )
                expect(mockTeamResolver.mock.calls).toEqual([expectedCalls])
            })
        })
    })

    it('minDefined', () => {
        expect(minDefined(1, 2, 3)).toEqual(1)
        expect(minDefined(1, undefined, 3)).toEqual(1)
        expect(minDefined(undefined, undefined, undefined)).toEqual(undefined)
        expect(maxDefined()).toEqual(undefined)
    })

    it('maxDefined', () => {
        expect(maxDefined(1, 2, 3)).toEqual(3)
        expect(maxDefined(1, undefined, 3)).toEqual(3)
        expect(maxDefined(undefined, undefined, undefined)).toEqual(undefined)
        expect(maxDefined()).toEqual(undefined)
    })

    describe('getLagMultiplier', () => {
        const threshold = 1000
        it('returns 1 when lag is 0', () => {
            expect(getLagMultiplier(0, threshold)).toEqual(1)
        })

        it('returns 1 when lag is under threshold', () => {
            expect(getLagMultiplier(threshold - 1, threshold)).toEqual(1)
        })

        it('returns 0.9 when lag is double threshold', () => {
            expect(getLagMultiplier(threshold * 2, threshold)).toEqual(0.9)
        })

        it('returns 0.6 when lag is 5 times the threshold', () => {
            expect(getLagMultiplier(threshold * 5, threshold)).toEqual(0.6)
        })

        it('returns 0.9 when lag is 9 times the threshold', () => {
            expect(getLagMultiplier(threshold * 9, threshold)).toBeGreaterThanOrEqual(0.19)
            expect(getLagMultiplier(threshold * 9, threshold)).toBeLessThanOrEqual(0.2)
        })

        it('returns 0.1 when lag is 100 times the threshold', () => {
            expect(getLagMultiplier(threshold * 100, threshold)).toEqual(0.1)
        })
    })

    describe('parseKafkaBatch', () => {
        let fakeProducer: KafkaProducerWrapper
        beforeEach(() => {
            Settings.now = () => new Date('2023-08-30T19:15:54.887316+00:00').getTime()
            fakeProducer = { queueMessages: jest.fn(() => Promise.resolve()) } as unknown as KafkaProducerWrapper
        })

        it('can parse and reduce a batch of messages', async () => {
            const sessions = [
                {
                    distinct_id: 'c3936f0b-875f-4992-8e8a-26499d1f3a0a',
                    $session_id: 'e38da031-6341-4db8-ab00-af04f91f9962',
                    $window_id: 'b8d205d5-dd89-4465-b2d5-eb4d1eceb3ea',
                },
                {
                    distinct_id: '207f0e52-f265-4932-86e5-cec62844d990',
                    $session_id: '1fc12a30-5a0f-4af8-808a-328423acf0c4',
                    $window_id: '0bbe7878-6516-46b2-80cf-e387839d7313',
                },
                {
                    distinct_id: '9696eba5-4f24-4f06-957b-10f98e26f2a9',
                    $session_id: 'cb91c812-98d0-4d5f-ae88-ffb68b7f51d3',
                    $window_id: '1260fae8-08b5-4e5f-bea1-b8abd6250b70',
                },
            ]
            const otherWindowId = 'c74d85fa-ccbb-43ba-981c-5e7d17f211de'
            const eventUuids = Array.from(Array(6), () => new UUIDT().toString())
            const headers = [{ token: Buffer.from('the_token') }]

            const messages: Message[] = [
                // Six messages for three sessions on two partitions, second is invalid.
                // The first session has three events on two windows.
                {
                    headers,
                    value: Buffer.from(
                        JSON.stringify({
                            uuid: eventUuids[0],
                            distinct_id: sessions[0].distinct_id,
                            ip: '127.0.0.1',
                            site_url: 'http://127.0.0.1:8000',
                            data: JSON.stringify({
                                uuid: eventUuids[0],
                                event: '$snapshot_items',
                                properties: {
                                    $lib: 'the value we will use',
                                    $snapshot_items: [
                                        {
                                            type: 6,
                                            data: {},
                                            timestamp: null, // Invalid, item will be skipped
                                        },
                                        {
                                            type: 6,
                                            data: {},
                                            timestamp: 123,
                                        },
                                    ],
                                    ...sessions[0],
                                },
                            }),
                            token: 'the_token',
                        })
                    ),
                    timestamp: 100,
                    size: 5,
                    topic: 'the_topic',
                    offset: 232,
                    partition: 1,
                },
                {
                    headers,
                    value: Buffer.from(
                        JSON.stringify({
                            uuid: eventUuids[1],
                            distinct_id: sessions[2].distinct_id,
                            ip: '127.0.0.1',
                            site_url: 'http://127.0.0.1:8000',
                            data: JSON.stringify({}), // Invalid, message will be skipped
                            token: 'the_token',
                        })
                    ),
                    timestamp: 96,
                    size: 100,
                    topic: 'the_topic',
                    offset: 499,
                    partition: 2,
                },
                {
                    headers,
                    value: Buffer.from(
                        JSON.stringify({
                            uuid: eventUuids[2],
                            distinct_id: sessions[1].distinct_id,
                            ip: '127.0.0.1',
                            site_url: 'http://127.0.0.1:8000',
                            data: JSON.stringify({
                                uuid: eventUuids[2],
                                event: '$snapshot_items',
                                properties: {
                                    $snapshot_items: [
                                        {
                                            data: {},
                                            timestamp: 222,
                                            type: 6,
                                        },
                                    ],
                                    ...sessions[1],
                                },
                            }),
                            token: 'the_token',
                        })
                    ),
                    timestamp: 101,
                    size: 30,
                    topic: 'the_topic',
                    offset: 233,
                    partition: 1,
                },
                {
                    headers,
                    value: Buffer.from(
                        JSON.stringify({
                            uuid: eventUuids[3],
                            distinct_id: sessions[2].distinct_id,
                            ip: '127.0.0.1',
                            site_url: 'http://127.0.0.1:8000',
                            data: JSON.stringify({
                                uuid: eventUuids[3],
                                event: '$snapshot_items',
                                properties: {
                                    $snapshot_items: [
                                        {
                                            data: {},
                                            timestamp: 432,
                                            type: 6,
                                        },
                                    ],
                                    ...sessions[2],
                                },
                            }),
                            token: 'the_token',
                        })
                    ),
                    timestamp: 98,
                    size: 100,
                    topic: 'the_topic',
                    offset: 500,
                    partition: 2,
                },
                {
                    headers,
                    value: Buffer.from(
                        JSON.stringify({
                            uuid: eventUuids[4],
                            distinct_id: sessions[0].distinct_id,
                            ip: '127.0.0.1',
                            site_url: 'http://127.0.0.1:8000',
                            data: JSON.stringify({
                                uuid: eventUuids[4],
                                event: '$snapshot_items',
                                properties: {
                                    $snapshot_items: [
                                        {
                                            data: {},
                                            timestamp: 433,
                                            type: 6,
                                        },
                                    ],
                                    ...sessions[0],
                                    $window_id: otherWindowId,
                                },
                            }),
                            token: 'the_token',
                        })
                    ),
                    timestamp: 106,
                    size: 4,
                    topic: 'the_topic',
                    offset: 234,
                    partition: 1,
                },
                {
                    headers,
                    value: Buffer.from(
                        JSON.stringify({
                            uuid: eventUuids[5],
                            distinct_id: sessions[0].distinct_id,
                            ip: '127.0.0.1',
                            site_url: 'http://127.0.0.1:8000',
                            data: JSON.stringify({
                                uuid: eventUuids[5],
                                event: '$snapshot_items',
                                properties: {
                                    $snapshot_items: [
                                        {
                                            data: {},
                                            timestamp: 438,
                                            type: 6,
                                        },
                                    ],
                                    ...sessions[0],
                                },
                            }),
                            token: 'the_token',
                        })
                    ),
                    timestamp: 107,
                    size: 4,
                    topic: 'the_topic',
                    offset: 235,
                    partition: 1,
                },
            ]

            const parsedBatch = await parseKafkaBatch(
                messages,
                () =>
                    Promise.resolve({
                        teamId: 1,
                        consoleLogIngestionEnabled: true,
                    }),
                fakeProducer
            )

            // Check returned partition statistics
            expect(parsedBatch.partitionStats).toHaveLength(2)
            parsedBatch.partitionStats.sort((a, b) => {
                return a.partition - b.partition
            })
            expect(parsedBatch.partitionStats[0]).toMatchObject({
                partition: 1,
                offset: 235,
                timestamp: 107,
            })
            expect(parsedBatch.partitionStats[1]).toMatchObject({
                partition: 2,
                offset: 500,
                timestamp: 98,
            })

            // Check aggregated session data
            expect(parsedBatch.sessions).toHaveLength(3)
            expect(parsedBatch.sessions[0].eventsByWindowId[sessions[0].$window_id]).toHaveLength(2)
            expect(parsedBatch.sessions[0].eventsByWindowId[otherWindowId]).toHaveLength(1)
            expect(parsedBatch.sessions).toMatchSnapshot()
        })

        it('does not merge sessions for different teams', async () => {
            const session = {
                distinct_id: 'c3936f0b-875f-4992-8e8a-26499d1f3a0a',
                $session_id: 'e38da031-6341-4db8-ab00-af04f91f9962',
                $window_id: 'b8d205d5-dd89-4465-b2d5-eb4d1eceb3ea',
            }
            const eventUuids = Array.from(Array(3), () => new UUIDT().toString())

            const messages: Message[] = [
                // Three messages with the same distinct_id and $session_id but two different tokens
                {
                    headers: [{ token: Buffer.from('one_token') }],
                    value: Buffer.from(
                        JSON.stringify({
                            uuid: eventUuids[0],
                            distinct_id: session.distinct_id,
                            ip: '127.0.0.1',
                            site_url: 'http://127.0.0.1:8000',
                            data: JSON.stringify({
                                uuid: eventUuids[0],
                                event: '$snapshot_items',
                                properties: {
                                    $snapshot_items: [
                                        {
                                            type: 6,
                                            data: {},
                                            timestamp: 123,
                                        },
                                    ],
                                    ...session,
                                },
                            }),
                            token: 'one_token',
                        })
                    ),
                    timestamp: 100,
                    size: 5,
                    topic: 'the_topic',
                    offset: 232,
                    partition: 1,
                },
                {
                    headers: [{ token: Buffer.from('one_token') }],
                    value: Buffer.from(
                        JSON.stringify({
                            uuid: eventUuids[0],
                            distinct_id: session.distinct_id,
                            ip: '127.0.0.1',
                            site_url: 'http://127.0.0.1:8000',
                            data: JSON.stringify({
                                uuid: eventUuids[0],
                                event: '$snapshot_items',
                                properties: {
                                    $snapshot_items: [
                                        {
                                            type: 6,
                                            data: {},
                                            timestamp: 124,
                                        },
                                    ],
                                    ...session,
                                },
                            }),
                            token: 'one_token',
                        })
                    ),
                    timestamp: 101,
                    size: 4,
                    topic: 'the_topic',
                    offset: 233,
                    partition: 1,
                },
                {
                    headers: [{ token: Buffer.from('another_token') }],
                    value: Buffer.from(
                        JSON.stringify({
                            uuid: eventUuids[0],
                            distinct_id: session.distinct_id,
                            ip: '127.0.0.1',
                            site_url: 'http://127.0.0.1:8000',
                            data: JSON.stringify({
                                uuid: eventUuids[0],
                                event: '$snapshot_items',
                                properties: {
                                    $snapshot_items: [
                                        {
                                            type: 6,
                                            data: {},
                                            timestamp: 127,
                                        },
                                    ],
                                    ...session,
                                },
                            }),
                            token: 'another_token',
                        })
                    ),
                    timestamp: 103,
                    size: 20,
                    topic: 'the_topic',
                    offset: 234,
                    partition: 1,
                },
            ]

            const parsedBatch = await parseKafkaBatch(
                messages,
                (token: string) =>
                    Promise.resolve({
                        teamId: token.length,
                        consoleLogIngestionEnabled: true,
                    }),
                fakeProducer
            )

            // Check aggregated session data
            expect(parsedBatch.sessions).toHaveLength(2)
            expect(parsedBatch.sessions[0].team_id).toEqual(9)
            expect(parsedBatch.sessions[1].team_id).toEqual(13)
            expect(parsedBatch.sessions).toMatchSnapshot()
        })
    })

    describe('allSettledWithConcurrency', () => {
        jest.setTimeout(1000)
        it('should resolve promises in parallel with a max consumption', async () => {
            let counter = 0
            const ids = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
            const waiters: Record<number, any> = {}

            const promise = allSettledWithConcurrency(4, ids, (id) => {
                return new Promise<any>((resolve, reject) => {
                    waiters[id] = { resolve, reject }
                }).finally(() => {
                    delete waiters[id]
                    counter++
                })
            })

            expect(Object.keys(waiters)).toEqual(['1', '2', '3', '4'])

            // Check less than the max concurrency
            waiters['1'].resolve(1)
            await new Promise((resolve) => setTimeout(resolve, 1))
            expect(Object.keys(waiters)).toEqual(['2', '3', '4', '5'])

            // check multiple resolves
            waiters['4'].resolve(4)
            waiters['2'].resolve(2)
            waiters['3'].resolve(3)
            await new Promise((resolve) => setTimeout(resolve, 1))
            expect(Object.keys(waiters)).toEqual(['5', '6', '7', '8'])

            // Check rejections
            waiters['5'].reject(5)
            waiters['6'].reject(6)
            waiters['7'].reject(7)
            waiters['8'].reject(8)
            await new Promise((resolve) => setTimeout(resolve, 1))
            expect(Object.keys(waiters)).toEqual(['9', '10'])
            waiters['9'].reject(9)
            waiters['10'].resolve(10)

            await expect(promise).resolves.toEqual([
                { result: 1 },
                { result: 2 },
                { result: 3 },
                { result: 4 },
                { error: 5 },
                { error: 6 },
                { error: 7 },
                { error: 8 },
                { error: 9 },
                { result: 10 },
            ])

            expect(counter).toEqual(10)
        })

        it('should allow breaking mid chain', async () => {
            const ids = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
            const waiters: Record<number, any> = {}

            const promise = allSettledWithConcurrency(4, ids, (id, ctx) => {
                return new Promise<any>((resolve, reject) => {
                    waiters[id] = {
                        resolve,
                        reject: () => {
                            ctx.break()
                            reject()
                        },
                    }
                }).finally(() => {
                    delete waiters[id]
                })
            })

            expect(Object.keys(waiters)).toEqual(['1', '2', '3', '4'])
            waiters[4].resolve(4)
            await new Promise((resolve) => setTimeout(resolve, 1))
            waiters[3].resolve(3)
            waiters[2].reject() // Triggers the break

            // We should see the promise that resolved before the break but not the other one
            await expect(promise).resolves.toEqual([undefined, undefined, undefined, { result: 4 }])
        })
    })
})
