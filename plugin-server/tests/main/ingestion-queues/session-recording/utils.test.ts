import { Message, MessageHeader } from 'node-rdkafka'

import {
    getLagMultiplier,
    maxDefined,
    minDefined,
    parseKafkaMessage,
} from '../../../../src/main/ingestion-queues/session-recording/utils'

describe('session-recording utils', () => {
    const validMessage = (distinctId: number | string, headers?: MessageHeader[], value?: Record<string, any>) =>
        ({
            headers,
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
            size: 1,
            topic: 'the_topic',
            offset: 1,
            partition: 1,
        } satisfies Message)

    describe('parsing the message', () => {
        it('can handle numeric distinct_ids', async () => {
            const numericId = 12345
            const parsedMessage = await parseKafkaMessage(validMessage(numericId), () =>
                Promise.resolve({ teamId: 1, consoleLogIngestionEnabled: false })
            )
            expect(parsedMessage).toEqual({
                distinct_id: String(numericId),
                events: expect.any(Array),
                metadata: {
                    offset: 1,
                    partition: 1,
                    timestamp: 1,
                    topic: 'the_topic',
                    consoleLogIngestionEnabled: false,
                },
                session_id: '018a47c2-2f4a-70a8-b480-5e51d8b8d070',
                team_id: 1,
                window_id: '018a47c2-2f4a-70a8-b480-5e52f5480448',
            })
        })

        it('filters out invalid rrweb events', async () => {
            const numeric_id = 12345

            const createMessage = ($snapshot_items: unknown[]) => {
                return {
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
                () => Promise.resolve({ teamId: 1, consoleLogIngestionEnabled: true })
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
                () => Promise.resolve({ teamId: 1, consoleLogIngestionEnabled: true })
            )
            expect(parsedMessage2).toMatchObject({
                events: [
                    {
                        data: {},
                        timestamp: 123,
                        type: 6,
                    },
                ],
            })

            const parsedMessage3 = await parseKafkaMessage(createMessage([null]), () =>
                Promise.resolve({ teamId: 1, consoleLogIngestionEnabled: false })
            )
            expect(parsedMessage3).toEqual(undefined)
        })

        describe('team token can be in header or body', () => {
            const mockTeamResolver = jest.fn()

            beforeEach(() => {
                mockTeamResolver.mockReset()
                mockTeamResolver.mockResolvedValue({ teamId: 1, consoleLogIngestionEnabled: false })
            })

            test.each([
                [
                    'calls the team id resolver once when token is in header, not in the body',
                    'the_token',
                    undefined,
                    ['the_token'],
                ],
                [
                    'calls the team id resolver once when token is in header, and in the body',
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
                    'calls the team id resolver twice when token is not in header, and is in body',
                    undefined,
                    'the body token',
                    ['the body token'],
                ],
            ])('%s', async (_name, headerToken, payloadToken, expectedCalls) => {
                await parseKafkaMessage(
                    validMessage(12345, headerToken ? [{ token: Buffer.from(headerToken) }] : undefined, {
                        token: payloadToken,
                    }),
                    mockTeamResolver
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
})
