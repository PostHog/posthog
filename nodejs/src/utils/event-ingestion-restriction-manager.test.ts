import { Pool as GenericPool } from 'generic-pool'
import { Redis } from 'ioredis'

import { RedisPool } from '../types'
import {
    EventIngestionRestrictionManager,
    REDIS_KEY_PREFIX,
    RedisRestrictionType,
    Restriction,
} from './event-ingestion-restriction-manager'

const createMockRedisPool = (): RedisPool => {
    const redisClient = {
        pipeline: jest.fn(),
        quit: jest.fn().mockResolvedValue(undefined),
    }

    return {
        acquire: jest.fn().mockResolvedValue(redisClient),
        release: jest.fn().mockResolvedValue(undefined),
    } as unknown as RedisPool
}

type DynamicConfigInput = {
    dropTokens?: string[]
    skipPersonTokens?: string[]
    forceOverflowTokens?: string[]
    redirectToDlqTokens?: string[]
}

function toRedisFormat(tokens: string[] | undefined, pipeline: string = 'analytics'): string | null {
    if (!tokens) {
        return null
    }
    return JSON.stringify(
        tokens.map((t) => {
            if (t.includes(':distinct_id:')) {
                const [token, , distinctId] = t.split(':')
                return { token, distinct_id: distinctId, pipelines: [pipeline] }
            } else if (t.includes(':session_id:')) {
                const [token, , sessionId] = t.split(':')
                return { token, session_id: sessionId, pipelines: [pipeline] }
            } else if (t.includes(':event_name:')) {
                const [token, , eventName] = t.split(':')
                return { token, event_name: eventName, pipelines: [pipeline] }
            } else if (t.includes(':event_uuid:')) {
                const [token, , eventUuid] = t.split(':')
                return { token, event_uuid: eventUuid, pipelines: [pipeline] }
            } else {
                return { token: t, pipelines: [pipeline] }
            }
        })
    )
}

function setupDynamicConfig(
    pipelineMock: any,
    manager: EventIngestionRestrictionManager,
    config: DynamicConfigInput
): Promise<void> {
    pipelineMock.exec.mockResolvedValueOnce([
        [null, toRedisFormat(config.dropTokens)],
        [null, toRedisFormat(config.skipPersonTokens)],
        [null, toRedisFormat(config.forceOverflowTokens)],
        [null, toRedisFormat(config.redirectToDlqTokens)],
    ])

    return manager.forceRefresh()
}

describe('EventIngestionRestrictionManager', () => {
    let hub: { redisPool: GenericPool<Redis> }
    let redisClient: Redis
    let pipelineMock: any
    let eventIngestionRestrictionManager: EventIngestionRestrictionManager

    beforeEach(async () => {
        pipelineMock = {
            get: jest.fn().mockReturnThis(),
            exec: jest.fn().mockResolvedValue([
                [null, null],
                [null, null],
                [null, null],
                [null, null],
            ]),
        }

        const redisPool = createMockRedisPool()
        redisClient = await redisPool.acquire()
        redisClient.pipeline = jest.fn().mockReturnValue(pipelineMock)

        hub = {
            redisPool: redisPool,
        }

        eventIngestionRestrictionManager = new EventIngestionRestrictionManager(hub.redisPool, {
            staticDropEventTokens: [],
            staticSkipPersonTokens: [],
            staticForceOverflowTokens: [],
        })
        jest.clearAllMocks()
    })

    afterEach(() => {
        jest.clearAllMocks()
    })

    describe('constructor', () => {
        it('initializes with default values if no options provided', () => {
            const manager = new EventIngestionRestrictionManager(hub.redisPool)
            expect(manager).toBeDefined()
        })

        it('initializes with provided options', () => {
            const manager = new EventIngestionRestrictionManager(hub.redisPool, {
                staticDropEventTokens: ['token1'],
                staticSkipPersonTokens: ['token2'],
                staticForceOverflowTokens: ['token3'],
            })
            expect(manager).toBeDefined()
        })
    })

    describe('dynamic config loading from Redis', () => {
        it('fetches and parses Redis data correctly', async () => {
            pipelineMock.exec.mockResolvedValueOnce([
                [
                    null,
                    JSON.stringify([
                        { token: 'token1', pipelines: ['analytics'] },
                        { token: 'token2', pipelines: ['analytics'] },
                    ]),
                ],
                [
                    null,
                    JSON.stringify([
                        { token: 'token3', pipelines: ['analytics'] },
                        { token: 'token4', pipelines: ['analytics'] },
                    ]),
                ],
                [
                    null,
                    JSON.stringify([
                        { token: 'token5', pipelines: ['analytics'] },
                        { token: 'token6', pipelines: ['analytics'] },
                    ]),
                ],
                [
                    null,
                    JSON.stringify([
                        { token: 'token7', pipelines: ['analytics'] },
                        { token: 'token8', pipelines: ['analytics'] },
                    ]),
                ],
            ])

            await eventIngestionRestrictionManager.forceRefresh()

            expect(eventIngestionRestrictionManager.getAppliedRestrictions('token1')).toContain(Restriction.DROP_EVENT)
            expect(eventIngestionRestrictionManager.getAppliedRestrictions('token2')).toContain(Restriction.DROP_EVENT)
            expect(eventIngestionRestrictionManager.getAppliedRestrictions('token3')).toContain(
                Restriction.SKIP_PERSON_PROCESSING
            )
            expect(eventIngestionRestrictionManager.getAppliedRestrictions('token4')).toContain(
                Restriction.SKIP_PERSON_PROCESSING
            )
            expect(eventIngestionRestrictionManager.getAppliedRestrictions('token5')).toContain(
                Restriction.FORCE_OVERFLOW
            )
            expect(eventIngestionRestrictionManager.getAppliedRestrictions('token6')).toContain(
                Restriction.FORCE_OVERFLOW
            )
            expect(eventIngestionRestrictionManager.getAppliedRestrictions('token7')).toContain(
                Restriction.REDIRECT_TO_DLQ
            )
            expect(eventIngestionRestrictionManager.getAppliedRestrictions('token8')).toContain(
                Restriction.REDIRECT_TO_DLQ
            )

            expect(hub.redisPool.acquire).toHaveBeenCalled()
            expect(pipelineMock.get).toHaveBeenCalledWith(
                `${REDIS_KEY_PREFIX}:${RedisRestrictionType.DROP_EVENT_FROM_INGESTION}`
            )
            expect(pipelineMock.get).toHaveBeenCalledWith(
                `${REDIS_KEY_PREFIX}:${RedisRestrictionType.SKIP_PERSON_PROCESSING}`
            )
            expect(pipelineMock.get).toHaveBeenCalledWith(
                `${REDIS_KEY_PREFIX}:${RedisRestrictionType.FORCE_OVERFLOW_FROM_INGESTION}`
            )
            expect(pipelineMock.get).toHaveBeenCalledWith(`${REDIS_KEY_PREFIX}:${RedisRestrictionType.REDIRECT_TO_DLQ}`)
            expect(hub.redisPool.release).toHaveBeenCalledWith(redisClient)
        })

        it('handles Redis errors gracefully', async () => {
            pipelineMock.exec.mockRejectedValueOnce(new Error('Redis error'))

            await eventIngestionRestrictionManager.forceRefresh()

            expect(eventIngestionRestrictionManager.getAppliedRestrictions('any-token')).toEqual(new Set())
            expect(hub.redisPool.release).toHaveBeenCalledWith(redisClient)
        })

        it('handles Redis pool acquisition errors gracefully', async () => {
            hub.redisPool.acquire = jest.fn().mockRejectedValueOnce(new Error('Pool error'))

            await eventIngestionRestrictionManager.forceRefresh()

            expect(eventIngestionRestrictionManager.getAppliedRestrictions('any-token')).toEqual(new Set())
        })

        it('handles new format with pipeline fields (analytics pipeline)', async () => {
            pipelineMock.exec.mockResolvedValueOnce([
                [
                    null,
                    JSON.stringify([
                        { token: 'token1', pipelines: ['analytics'] },
                        { token: 'token2', distinct_id: 'user1', pipelines: ['analytics', 'session_recordings'] },
                        { token: 'token3', pipelines: ['session_recordings'] },
                    ]),
                ],
                [null, null],
                [null, null],
                [null, null],
            ])

            await eventIngestionRestrictionManager.forceRefresh()

            expect(eventIngestionRestrictionManager.getAppliedRestrictions('token1')).toContain(Restriction.DROP_EVENT)
            expect(
                eventIngestionRestrictionManager.getAppliedRestrictions('token2', { distinct_id: 'user1' })
            ).toContain(Restriction.DROP_EVENT)
            expect(eventIngestionRestrictionManager.getAppliedRestrictions('token3')).toEqual(new Set())
        })

        it('handles new format with only session_recordings enabled (analytics pipeline)', async () => {
            pipelineMock.exec.mockResolvedValueOnce([
                [null, JSON.stringify([{ token: 'token1', pipelines: ['session_recordings'] }])],
                [null, null],
                [null, null],
                [null, null],
            ])

            await eventIngestionRestrictionManager.forceRefresh()

            expect(eventIngestionRestrictionManager.getAppliedRestrictions('token1')).toEqual(new Set())
        })

        it('excludes entries with empty pipelines array', async () => {
            pipelineMock.exec.mockResolvedValueOnce([
                [
                    null,
                    JSON.stringify([
                        { token: 'token1', pipelines: [] },
                        { token: 'token2', pipelines: ['analytics'] },
                    ]),
                ],
                [null, null],
                [null, null],
                [null, null],
            ])

            await eventIngestionRestrictionManager.forceRefresh()

            expect(eventIngestionRestrictionManager.getAppliedRestrictions('token1')).toEqual(new Set())
            expect(eventIngestionRestrictionManager.getAppliedRestrictions('token2')).toContain(Restriction.DROP_EVENT)
        })

        it('excludes entries when pipeline field is missing', async () => {
            pipelineMock.exec.mockResolvedValueOnce([
                [null, JSON.stringify([{ token: 'token1' }, { token: 'token2', pipelines: ['analytics'] }])],
                [null, null],
                [null, null],
                [null, null],
            ])

            await eventIngestionRestrictionManager.forceRefresh()

            expect(eventIngestionRestrictionManager.getAppliedRestrictions('token1')).toEqual(new Set())
            expect(eventIngestionRestrictionManager.getAppliedRestrictions('token2')).toContain(Restriction.DROP_EVENT)
        })

        it('filters by session_recordings pipeline', async () => {
            pipelineMock.exec.mockResolvedValueOnce([
                [
                    null,
                    JSON.stringify([
                        { token: 'token1', pipelines: ['analytics'] },
                        { token: 'token2', pipelines: ['session_recordings'] },
                        { token: 'token3', pipelines: ['analytics', 'session_recordings'] },
                    ]),
                ],
                [null, null],
                [null, null],
                [null, null],
            ])

            const manager = new EventIngestionRestrictionManager(hub.redisPool, {
                pipeline: 'session_recordings',
            })
            await manager.forceRefresh()

            expect(manager.getAppliedRestrictions('token1')).toEqual(new Set())
            expect(manager.getAppliedRestrictions('token2')).toContain(Restriction.DROP_EVENT)
            expect(manager.getAppliedRestrictions('token3')).toContain(Restriction.DROP_EVENT)
        })
    })

    describe('getAppliedRestrictions - DROP_EVENT', () => {
        it('returns empty array if token is not provided', () => {
            expect(eventIngestionRestrictionManager.getAppliedRestrictions()).toEqual(new Set())
        })

        it('includes DROP_EVENT if token is in static drop list', async () => {
            eventIngestionRestrictionManager = new EventIngestionRestrictionManager(hub.redisPool, {
                staticDropEventTokens: ['static-drop-token'],
            })
            await eventIngestionRestrictionManager.forceRefresh()
            expect(eventIngestionRestrictionManager.getAppliedRestrictions('static-drop-token')).toContain(
                Restriction.DROP_EVENT
            )
        })

        it('includes DROP_EVENT if token:distinctId is in static drop list', async () => {
            eventIngestionRestrictionManager = new EventIngestionRestrictionManager(hub.redisPool, {
                staticDropEventTokens: ['static-drop-token:distinct_id:123'],
            })
            await eventIngestionRestrictionManager.forceRefresh()
            expect(
                eventIngestionRestrictionManager.getAppliedRestrictions('static-drop-token', { distinct_id: '123' })
            ).toContain(Restriction.DROP_EVENT)
        })

        it('returns empty array if dynamic set is not defined', async () => {
            pipelineMock.exec.mockResolvedValueOnce([
                [null, null],
                [null, null],
                [null, null],
                [null, null],
            ])
            await eventIngestionRestrictionManager.forceRefresh()
            expect(eventIngestionRestrictionManager.getAppliedRestrictions('token')).toEqual(new Set())
        })

        it('includes DROP_EVENT if token is in the dynamic config list', async () => {
            await setupDynamicConfig(pipelineMock, eventIngestionRestrictionManager, {
                dropTokens: ['token'],
            })
            expect(eventIngestionRestrictionManager.getAppliedRestrictions('token')).toContain(Restriction.DROP_EVENT)
        })

        it('includes DROP_EVENT if distinctId is in the dynamic config list', async () => {
            await setupDynamicConfig(pipelineMock, eventIngestionRestrictionManager, {
                dropTokens: ['token:distinct_id:123'],
            })
            expect(eventIngestionRestrictionManager.getAppliedRestrictions('token', { distinct_id: '123' })).toContain(
                Restriction.DROP_EVENT
            )
        })

        it('does not include DROP_EVENT if neither token nor distinctId is in the dynamic config list', async () => {
            await setupDynamicConfig(pipelineMock, eventIngestionRestrictionManager, {
                dropTokens: ['other-token', 'token:distinct_id:789'],
            })
            expect(
                eventIngestionRestrictionManager.getAppliedRestrictions('token', { distinct_id: '123' })
            ).not.toContain(Restriction.DROP_EVENT)
        })
    })

    describe('getAppliedRestrictions - SKIP_PERSON_PROCESSING', () => {
        it('returns empty array if token is not provided', () => {
            expect(eventIngestionRestrictionManager.getAppliedRestrictions()).toEqual(new Set())
        })

        it('includes SKIP_PERSON_PROCESSING if token is in static skip list', async () => {
            eventIngestionRestrictionManager = new EventIngestionRestrictionManager(hub.redisPool, {
                staticSkipPersonTokens: ['static-skip-token'],
            })
            await eventIngestionRestrictionManager.forceRefresh()
            expect(eventIngestionRestrictionManager.getAppliedRestrictions('static-skip-token')).toContain(
                Restriction.SKIP_PERSON_PROCESSING
            )
        })

        it('includes SKIP_PERSON_PROCESSING if token:distinctId is in static skip list', async () => {
            eventIngestionRestrictionManager = new EventIngestionRestrictionManager(hub.redisPool, {
                staticSkipPersonTokens: ['static-skip-token:distinct_id:123'],
            })
            await eventIngestionRestrictionManager.forceRefresh()
            expect(
                eventIngestionRestrictionManager.getAppliedRestrictions('static-skip-token', { distinct_id: '123' })
            ).toContain(Restriction.SKIP_PERSON_PROCESSING)
        })

        it('returns empty array if dynamic set is not defined', async () => {
            pipelineMock.exec.mockResolvedValueOnce([
                [null, null],
                [null, null],
                [null, null],
                [null, null],
            ])
            await eventIngestionRestrictionManager.forceRefresh()
            expect(eventIngestionRestrictionManager.getAppliedRestrictions('token')).toEqual(new Set())
        })

        it('includes SKIP_PERSON_PROCESSING if token is in the dynamic config list', async () => {
            await setupDynamicConfig(pipelineMock, eventIngestionRestrictionManager, {
                skipPersonTokens: ['token'],
            })
            expect(eventIngestionRestrictionManager.getAppliedRestrictions('token')).toContain(
                Restriction.SKIP_PERSON_PROCESSING
            )
        })

        it('includes SKIP_PERSON_PROCESSING if distinctId is in the dynamic config list', async () => {
            await setupDynamicConfig(pipelineMock, eventIngestionRestrictionManager, {
                skipPersonTokens: ['token:distinct_id:123'],
            })
            expect(eventIngestionRestrictionManager.getAppliedRestrictions('token', { distinct_id: '123' })).toContain(
                Restriction.SKIP_PERSON_PROCESSING
            )
        })

        it('does not include SKIP_PERSON_PROCESSING if neither token nor distinctId is in the dynamic config list', async () => {
            await setupDynamicConfig(pipelineMock, eventIngestionRestrictionManager, {
                skipPersonTokens: ['other-token', 'token:distinct_id:789'],
            })
            expect(
                eventIngestionRestrictionManager.getAppliedRestrictions('token', { distinct_id: '123' })
            ).not.toContain(Restriction.SKIP_PERSON_PROCESSING)
        })
    })

    describe('getAppliedRestrictions - FORCE_OVERFLOW', () => {
        it('returns empty array if token is not provided', () => {
            expect(eventIngestionRestrictionManager.getAppliedRestrictions()).toEqual(new Set())
        })

        it('includes FORCE_OVERFLOW if token is in static overflow list', async () => {
            eventIngestionRestrictionManager = new EventIngestionRestrictionManager(hub.redisPool, {
                staticForceOverflowTokens: ['static-overflow-token'],
            })
            await eventIngestionRestrictionManager.forceRefresh()
            expect(eventIngestionRestrictionManager.getAppliedRestrictions('static-overflow-token')).toContain(
                Restriction.FORCE_OVERFLOW
            )
        })

        it('includes FORCE_OVERFLOW if token:distinctId is in static overflow list', async () => {
            eventIngestionRestrictionManager = new EventIngestionRestrictionManager(hub.redisPool, {
                staticForceOverflowTokens: ['static-overflow-token:distinct_id:123'],
            })
            await eventIngestionRestrictionManager.forceRefresh()
            expect(
                eventIngestionRestrictionManager.getAppliedRestrictions('static-overflow-token', { distinct_id: '123' })
            ).toContain(Restriction.FORCE_OVERFLOW)
        })

        it('returns empty array if dynamic set is not defined', async () => {
            pipelineMock.exec.mockResolvedValueOnce([
                [null, null],
                [null, null],
                [null, null],
                [null, null],
            ])
            await eventIngestionRestrictionManager.forceRefresh()
            expect(eventIngestionRestrictionManager.getAppliedRestrictions('token')).toEqual(new Set())
        })

        it('includes FORCE_OVERFLOW if token is in the dynamic config list', async () => {
            await setupDynamicConfig(pipelineMock, eventIngestionRestrictionManager, {
                forceOverflowTokens: ['token'],
            })
            expect(eventIngestionRestrictionManager.getAppliedRestrictions('token')).toContain(
                Restriction.FORCE_OVERFLOW
            )
        })

        it('includes FORCE_OVERFLOW if distinctId is in the dynamic config list', async () => {
            await setupDynamicConfig(pipelineMock, eventIngestionRestrictionManager, {
                forceOverflowTokens: ['token:distinct_id:123'],
            })
            expect(eventIngestionRestrictionManager.getAppliedRestrictions('token', { distinct_id: '123' })).toContain(
                Restriction.FORCE_OVERFLOW
            )
        })

        it('does not include FORCE_OVERFLOW if neither token nor distinctId is in the dynamic config list', async () => {
            await setupDynamicConfig(pipelineMock, eventIngestionRestrictionManager, {
                forceOverflowTokens: ['other-token', 'token:distinct_id:789'],
            })
            expect(
                eventIngestionRestrictionManager.getAppliedRestrictions('token', { distinct_id: '123' })
            ).not.toContain(Restriction.FORCE_OVERFLOW)
        })
    })

    describe('getAppliedRestrictions - REDIRECT_TO_DLQ', () => {
        it('returns empty array if token is not provided', () => {
            expect(eventIngestionRestrictionManager.getAppliedRestrictions()).toEqual(new Set())
        })

        it('includes REDIRECT_TO_DLQ if token is in static DLQ list', async () => {
            eventIngestionRestrictionManager = new EventIngestionRestrictionManager(hub.redisPool, {
                staticRedirectToDlqTokens: ['static-dlq-token'],
            })
            await eventIngestionRestrictionManager.forceRefresh()
            expect(eventIngestionRestrictionManager.getAppliedRestrictions('static-dlq-token')).toContain(
                Restriction.REDIRECT_TO_DLQ
            )
        })

        it('includes REDIRECT_TO_DLQ if token:distinctId is in static DLQ list', async () => {
            eventIngestionRestrictionManager = new EventIngestionRestrictionManager(hub.redisPool, {
                staticRedirectToDlqTokens: ['static-dlq-token:distinct_id:123'],
            })
            await eventIngestionRestrictionManager.forceRefresh()
            expect(
                eventIngestionRestrictionManager.getAppliedRestrictions('static-dlq-token', { distinct_id: '123' })
            ).toContain(Restriction.REDIRECT_TO_DLQ)
        })

        it('returns empty array if dynamic set is not defined', async () => {
            pipelineMock.exec.mockResolvedValueOnce([
                [null, null],
                [null, null],
                [null, null],
                [null, null],
            ])
            await eventIngestionRestrictionManager.forceRefresh()
            expect(eventIngestionRestrictionManager.getAppliedRestrictions('token')).toEqual(new Set())
        })

        it('includes REDIRECT_TO_DLQ if token is in the dynamic config list', async () => {
            await setupDynamicConfig(pipelineMock, eventIngestionRestrictionManager, {
                redirectToDlqTokens: ['token'],
            })
            expect(eventIngestionRestrictionManager.getAppliedRestrictions('token')).toContain(
                Restriction.REDIRECT_TO_DLQ
            )
        })

        it('includes REDIRECT_TO_DLQ if distinctId is in the dynamic config list', async () => {
            await setupDynamicConfig(pipelineMock, eventIngestionRestrictionManager, {
                redirectToDlqTokens: ['token:distinct_id:123'],
            })
            expect(eventIngestionRestrictionManager.getAppliedRestrictions('token', { distinct_id: '123' })).toContain(
                Restriction.REDIRECT_TO_DLQ
            )
        })

        it('does not include REDIRECT_TO_DLQ if neither token nor distinctId is in the dynamic config list', async () => {
            await setupDynamicConfig(pipelineMock, eventIngestionRestrictionManager, {
                redirectToDlqTokens: ['other-token', 'token:distinct_id:789'],
            })
            expect(
                eventIngestionRestrictionManager.getAppliedRestrictions('token', { distinct_id: '123' })
            ).not.toContain(Restriction.REDIRECT_TO_DLQ)
        })

        it('includes REDIRECT_TO_DLQ if session_id is in the dynamic config list', async () => {
            await setupDynamicConfig(pipelineMock, eventIngestionRestrictionManager, {
                redirectToDlqTokens: ['token:session_id:session123'],
            })
            expect(
                eventIngestionRestrictionManager.getAppliedRestrictions('token', { session_id: 'session123' })
            ).toContain(Restriction.REDIRECT_TO_DLQ)
        })

        it('includes REDIRECT_TO_DLQ if event_name is in the dynamic config list', async () => {
            await setupDynamicConfig(pipelineMock, eventIngestionRestrictionManager, {
                redirectToDlqTokens: ['token:event_name:$pageview'],
            })
            expect(eventIngestionRestrictionManager.getAppliedRestrictions('token', { event: '$pageview' })).toContain(
                Restriction.REDIRECT_TO_DLQ
            )
        })

        it('includes REDIRECT_TO_DLQ if event_uuid is in the dynamic config list', async () => {
            await setupDynamicConfig(pipelineMock, eventIngestionRestrictionManager, {
                redirectToDlqTokens: ['token:event_uuid:uuid-123'],
            })
            expect(eventIngestionRestrictionManager.getAppliedRestrictions('token', { uuid: 'uuid-123' })).toContain(
                Restriction.REDIRECT_TO_DLQ
            )
        })
    })

    describe('session_id support', () => {
        describe('Redis parsing with session_ids', () => {
            it('handles new format with session_id field', async () => {
                pipelineMock.exec.mockResolvedValueOnce([
                    [
                        null,
                        JSON.stringify([
                            { token: 'token1', session_id: 'session123', pipelines: ['analytics'] },
                            { token: 'token2', distinct_id: 'user1', pipelines: ['analytics'] },
                        ]),
                    ],
                    [null, null],
                    [null, null],
                    [null, null],
                ])

                await eventIngestionRestrictionManager.forceRefresh()

                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token1', { session_id: 'session123' })
                ).toContain(Restriction.DROP_EVENT)
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token2', { distinct_id: 'user1' })
                ).toContain(Restriction.DROP_EVENT)
            })

            it('handles mixed distinct_id and session_id entries', async () => {
                pipelineMock.exec.mockResolvedValueOnce([
                    [
                        null,
                        JSON.stringify([
                            { token: 'token1', distinct_id: 'user1', pipelines: ['analytics'] },
                            { token: 'token1', session_id: 'session123', pipelines: ['analytics'] },
                            { token: 'token2', pipelines: ['analytics'] },
                        ]),
                    ],
                    [null, null],
                    [null, null],
                    [null, null],
                ])

                await eventIngestionRestrictionManager.forceRefresh()

                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token1', { distinct_id: 'user1' })
                ).toContain(Restriction.DROP_EVENT)
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token1', { session_id: 'session123' })
                ).toContain(Restriction.DROP_EVENT)
                expect(eventIngestionRestrictionManager.getAppliedRestrictions('token2')).toContain(
                    Restriction.DROP_EVENT
                )
            })
        })

        describe('getAppliedRestrictions with session_id - DROP_EVENT', () => {
            it('includes DROP_EVENT if session_id is in the dynamic config list', async () => {
                await setupDynamicConfig(pipelineMock, eventIngestionRestrictionManager, {
                    dropTokens: ['token:session_id:session123'],
                })
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token', { session_id: 'session123' })
                ).toContain(Restriction.DROP_EVENT)
            })

            it('includes DROP_EVENT if either distinct_id OR session_id matches (OR logic)', async () => {
                await setupDynamicConfig(pipelineMock, eventIngestionRestrictionManager, {
                    dropTokens: ['token:distinct_id:user1', 'token:session_id:session123'],
                })
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token', {
                        distinct_id: 'user1',
                        session_id: 'other-session',
                    })
                ).toContain(Restriction.DROP_EVENT)
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token', {
                        distinct_id: 'other-user',
                        session_id: 'session123',
                    })
                ).toContain(Restriction.DROP_EVENT)
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token', {
                        distinct_id: 'other-user',
                        session_id: 'other-session',
                    })
                ).not.toContain(Restriction.DROP_EVENT)
            })

            it('does not include DROP_EVENT if session_id does not match', async () => {
                await setupDynamicConfig(pipelineMock, eventIngestionRestrictionManager, {
                    dropTokens: ['token:session_id:session123'],
                })
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token', { session_id: 'other-session' })
                ).not.toContain(Restriction.DROP_EVENT)
            })
        })

        describe('getAppliedRestrictions with session_id - SKIP_PERSON_PROCESSING', () => {
            it('includes SKIP_PERSON_PROCESSING if session_id is in the dynamic config list', async () => {
                await setupDynamicConfig(pipelineMock, eventIngestionRestrictionManager, {
                    skipPersonTokens: ['token:session_id:session123'],
                })
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token', { session_id: 'session123' })
                ).toContain(Restriction.SKIP_PERSON_PROCESSING)
            })

            it('includes SKIP_PERSON_PROCESSING if either distinct_id OR session_id matches (OR logic)', async () => {
                await setupDynamicConfig(pipelineMock, eventIngestionRestrictionManager, {
                    skipPersonTokens: ['token:distinct_id:user1', 'token:session_id:session123'],
                })
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token', {
                        distinct_id: 'user1',
                        session_id: 'other-session',
                    })
                ).toContain(Restriction.SKIP_PERSON_PROCESSING)
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token', {
                        distinct_id: 'other-user',
                        session_id: 'session123',
                    })
                ).toContain(Restriction.SKIP_PERSON_PROCESSING)
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token', {
                        distinct_id: 'other-user',
                        session_id: 'other-session',
                    })
                ).not.toContain(Restriction.SKIP_PERSON_PROCESSING)
            })
        })

        describe('getAppliedRestrictions with session_id - FORCE_OVERFLOW', () => {
            it('includes FORCE_OVERFLOW if session_id is in the dynamic config list', async () => {
                await setupDynamicConfig(pipelineMock, eventIngestionRestrictionManager, {
                    forceOverflowTokens: ['token:session_id:session123'],
                })
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token', { session_id: 'session123' })
                ).toContain(Restriction.FORCE_OVERFLOW)
            })

            it('includes FORCE_OVERFLOW if either distinct_id OR session_id matches (OR logic)', async () => {
                await setupDynamicConfig(pipelineMock, eventIngestionRestrictionManager, {
                    forceOverflowTokens: ['token:distinct_id:user1', 'token:session_id:session123'],
                })
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token', {
                        distinct_id: 'user1',
                        session_id: 'other-session',
                    })
                ).toContain(Restriction.FORCE_OVERFLOW)
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token', {
                        distinct_id: 'other-user',
                        session_id: 'session123',
                    })
                ).toContain(Restriction.FORCE_OVERFLOW)
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token', {
                        distinct_id: 'other-user',
                        session_id: 'other-session',
                    })
                ).not.toContain(Restriction.FORCE_OVERFLOW)
            })
        })
    })

    describe('event_name support', () => {
        describe('Redis parsing with event_name', () => {
            it('handles new format with event_name field', async () => {
                pipelineMock.exec.mockResolvedValueOnce([
                    [
                        null,
                        JSON.stringify([
                            { token: 'token1', event: '$pageview', pipelines: ['analytics'] },
                            { token: 'token2', distinct_id: 'user1', pipelines: ['analytics'] },
                        ]),
                    ],
                    [null, null],
                    [null, null],
                    [null, null],
                ])

                await eventIngestionRestrictionManager.forceRefresh()

                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token1', { event: '$pageview' })
                ).toContain(Restriction.DROP_EVENT)
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token2', { distinct_id: 'user1' })
                ).toContain(Restriction.DROP_EVENT)
            })

            it('handles mixed distinct_id, session_id, and event_name entries', async () => {
                pipelineMock.exec.mockResolvedValueOnce([
                    [
                        null,
                        JSON.stringify([
                            { token: 'token1', distinct_id: 'user1', pipelines: ['analytics'] },
                            { token: 'token1', session_id: 'session123', pipelines: ['analytics'] },
                            { token: 'token1', event: '$pageview', pipelines: ['analytics'] },
                            { token: 'token2', pipelines: ['analytics'] },
                        ]),
                    ],
                    [null, null],
                    [null, null],
                    [null, null],
                ])

                await eventIngestionRestrictionManager.forceRefresh()

                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token1', { distinct_id: 'user1' })
                ).toContain(Restriction.DROP_EVENT)
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token1', { session_id: 'session123' })
                ).toContain(Restriction.DROP_EVENT)
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token1', { event: '$pageview' })
                ).toContain(Restriction.DROP_EVENT)
                expect(eventIngestionRestrictionManager.getAppliedRestrictions('token2')).toContain(
                    Restriction.DROP_EVENT
                )
            })
        })

        describe('getAppliedRestrictions with event_name - DROP_EVENT', () => {
            it('includes DROP_EVENT if event_name is in the dynamic config list', async () => {
                await setupDynamicConfig(pipelineMock, eventIngestionRestrictionManager, {
                    dropTokens: ['token:event_name:$pageview'],
                })
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token', { event: '$pageview' })
                ).toContain(Restriction.DROP_EVENT)
            })

            it('includes DROP_EVENT if any filter matches (OR logic)', async () => {
                await setupDynamicConfig(pipelineMock, eventIngestionRestrictionManager, {
                    dropTokens: [
                        'token:distinct_id:user1',
                        'token:session_id:session123',
                        'token:event_name:$pageview',
                    ],
                })
                // Match by distinct_id
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token', {
                        distinct_id: 'user1',
                        session_id: 'other-session',
                        event: 'other-event',
                    })
                ).toContain(Restriction.DROP_EVENT)
                // Match by session_id
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token', {
                        distinct_id: 'other-user',
                        session_id: 'session123',
                        event: 'other-event',
                    })
                ).toContain(Restriction.DROP_EVENT)
                // Match by event_name
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token', {
                        distinct_id: 'other-user',
                        session_id: 'other-session',
                        event: '$pageview',
                    })
                ).toContain(Restriction.DROP_EVENT)
                // No match
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token', {
                        distinct_id: 'other-user',
                        session_id: 'other-session',
                        event: 'other-event',
                    })
                ).not.toContain(Restriction.DROP_EVENT)
            })

            it('does not include DROP_EVENT if event_name does not match', async () => {
                await setupDynamicConfig(pipelineMock, eventIngestionRestrictionManager, {
                    dropTokens: ['token:event_name:$pageview'],
                })
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token', { event: '$autocapture' })
                ).not.toContain(Restriction.DROP_EVENT)
            })
        })

        describe('getAppliedRestrictions with event_name - SKIP_PERSON_PROCESSING', () => {
            it('includes SKIP_PERSON_PROCESSING if event_name is in the dynamic config list', async () => {
                await setupDynamicConfig(pipelineMock, eventIngestionRestrictionManager, {
                    skipPersonTokens: ['token:event_name:$pageview'],
                })
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token', { event: '$pageview' })
                ).toContain(Restriction.SKIP_PERSON_PROCESSING)
            })

            it('includes SKIP_PERSON_PROCESSING if any filter matches (OR logic)', async () => {
                await setupDynamicConfig(pipelineMock, eventIngestionRestrictionManager, {
                    skipPersonTokens: ['token:distinct_id:user1', 'token:event_name:$pageview'],
                })
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token', {
                        distinct_id: 'user1',
                        session_id: 'other-session',
                        event: 'other-event',
                    })
                ).toContain(Restriction.SKIP_PERSON_PROCESSING)
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token', {
                        distinct_id: 'other-user',
                        session_id: 'other-session',
                        event: '$pageview',
                    })
                ).toContain(Restriction.SKIP_PERSON_PROCESSING)
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token', {
                        distinct_id: 'other-user',
                        session_id: 'other-session',
                        event: 'other-event',
                    })
                ).not.toContain(Restriction.SKIP_PERSON_PROCESSING)
            })
        })

        describe('getAppliedRestrictions with event_name - FORCE_OVERFLOW', () => {
            it('includes FORCE_OVERFLOW if event_name is in the dynamic config list', async () => {
                await setupDynamicConfig(pipelineMock, eventIngestionRestrictionManager, {
                    forceOverflowTokens: ['token:event_name:$pageview'],
                })
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token', { event: '$pageview' })
                ).toContain(Restriction.FORCE_OVERFLOW)
            })

            it('includes FORCE_OVERFLOW if any filter matches (OR logic)', async () => {
                await setupDynamicConfig(pipelineMock, eventIngestionRestrictionManager, {
                    forceOverflowTokens: ['token:distinct_id:user1', 'token:event_name:$pageview'],
                })
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token', {
                        distinct_id: 'user1',
                        session_id: 'other-session',
                        event: 'other-event',
                    })
                ).toContain(Restriction.FORCE_OVERFLOW)
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token', {
                        distinct_id: 'other-user',
                        session_id: 'other-session',
                        event: '$pageview',
                    })
                ).toContain(Restriction.FORCE_OVERFLOW)
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token', {
                        distinct_id: 'other-user',
                        session_id: 'other-session',
                        event: 'other-event',
                    })
                ).not.toContain(Restriction.FORCE_OVERFLOW)
            })
        })
    })

    describe('event_uuid support', () => {
        describe('Redis parsing with event_uuid', () => {
            it('handles new format with event_uuid field', async () => {
                pipelineMock.exec.mockResolvedValueOnce([
                    [
                        null,
                        JSON.stringify([
                            {
                                token: 'token1',
                                uuid: '550e8400-e29b-41d4-a716-446655440000',
                                pipelines: ['analytics'],
                            },
                            { token: 'token2', pipelines: ['analytics'] },
                        ]),
                    ],
                    [null, null],
                    [null, null],
                    [null, null],
                ])

                await eventIngestionRestrictionManager.forceRefresh()

                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token1', {
                        uuid: '550e8400-e29b-41d4-a716-446655440000',
                    })
                ).toContain(Restriction.DROP_EVENT)
                expect(eventIngestionRestrictionManager.getAppliedRestrictions('token2')).toContain(
                    Restriction.DROP_EVENT
                )
            })

            it('handles mixed distinct_id, session_id, and event_uuid entries', async () => {
                pipelineMock.exec.mockResolvedValueOnce([
                    [
                        null,
                        JSON.stringify([
                            { token: 'token1', distinct_id: 'user1', pipelines: ['analytics'] },
                            { token: 'token1', session_id: 'session123', pipelines: ['analytics'] },
                            { token: 'token1', uuid: 'uuid-123', pipelines: ['analytics'] },
                            { token: 'token2', pipelines: ['analytics'] },
                        ]),
                    ],
                    [null, null],
                    [null, null],
                    [null, null],
                ])

                await eventIngestionRestrictionManager.forceRefresh()

                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token1', { distinct_id: 'user1' })
                ).toContain(Restriction.DROP_EVENT)
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token1', { session_id: 'session123' })
                ).toContain(Restriction.DROP_EVENT)
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token1', { uuid: 'uuid-123' })
                ).toContain(Restriction.DROP_EVENT)
                expect(eventIngestionRestrictionManager.getAppliedRestrictions('token2')).toContain(
                    Restriction.DROP_EVENT
                )
            })
        })

        describe('getAppliedRestrictions with event_uuid - DROP_EVENT', () => {
            it('includes DROP_EVENT if event_uuid is in the dynamic config list', async () => {
                await setupDynamicConfig(pipelineMock, eventIngestionRestrictionManager, {
                    dropTokens: ['token:event_uuid:uuid-123'],
                })
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token', { uuid: 'uuid-123' })
                ).toContain(Restriction.DROP_EVENT)
            })

            it('includes DROP_EVENT if any filter matches (OR logic)', async () => {
                await setupDynamicConfig(pipelineMock, eventIngestionRestrictionManager, {
                    dropTokens: ['token:distinct_id:user1', 'token:session_id:session123', 'token:event_uuid:uuid-123'],
                })
                // Match by distinct_id
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token', {
                        distinct_id: 'user1',
                        session_id: 'other-session',
                        uuid: 'other-uuid',
                    })
                ).toContain(Restriction.DROP_EVENT)
                // Match by session_id
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token', {
                        distinct_id: 'other-user',
                        session_id: 'session123',
                        uuid: 'other-uuid',
                    })
                ).toContain(Restriction.DROP_EVENT)
                // Match by event_uuid
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token', {
                        distinct_id: 'other-user',
                        session_id: 'other-session',
                        uuid: 'uuid-123',
                    })
                ).toContain(Restriction.DROP_EVENT)
                // No match
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token', {
                        distinct_id: 'other-user',
                        session_id: 'other-session',
                        uuid: 'other-uuid',
                    })
                ).not.toContain(Restriction.DROP_EVENT)
            })

            it('does not include DROP_EVENT if event_uuid does not match', async () => {
                await setupDynamicConfig(pipelineMock, eventIngestionRestrictionManager, {
                    dropTokens: ['token:event_uuid:uuid-123'],
                })
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token', { uuid: 'other-uuid' })
                ).not.toContain(Restriction.DROP_EVENT)
            })
        })

        describe('getAppliedRestrictions with event_uuid - SKIP_PERSON_PROCESSING', () => {
            it('includes SKIP_PERSON_PROCESSING if event_uuid is in the dynamic config list', async () => {
                await setupDynamicConfig(pipelineMock, eventIngestionRestrictionManager, {
                    skipPersonTokens: ['token:event_uuid:uuid-123'],
                })
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token', { uuid: 'uuid-123' })
                ).toContain(Restriction.SKIP_PERSON_PROCESSING)
            })

            it('includes SKIP_PERSON_PROCESSING if any filter matches (OR logic)', async () => {
                await setupDynamicConfig(pipelineMock, eventIngestionRestrictionManager, {
                    skipPersonTokens: ['token:distinct_id:user1', 'token:event_uuid:uuid-123'],
                })
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token', {
                        distinct_id: 'user1',
                        session_id: 'other-session',
                        uuid: 'other-uuid',
                    })
                ).toContain(Restriction.SKIP_PERSON_PROCESSING)
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token', {
                        distinct_id: 'other-user',
                        session_id: 'other-session',
                        uuid: 'uuid-123',
                    })
                ).toContain(Restriction.SKIP_PERSON_PROCESSING)
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token', {
                        distinct_id: 'other-user',
                        session_id: 'other-session',
                        uuid: 'other-uuid',
                    })
                ).not.toContain(Restriction.SKIP_PERSON_PROCESSING)
            })
        })

        describe('getAppliedRestrictions with event_uuid - FORCE_OVERFLOW', () => {
            it('includes FORCE_OVERFLOW if event_uuid is in the dynamic config list', async () => {
                await setupDynamicConfig(pipelineMock, eventIngestionRestrictionManager, {
                    forceOverflowTokens: ['token:event_uuid:uuid-123'],
                })
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token', { uuid: 'uuid-123' })
                ).toContain(Restriction.FORCE_OVERFLOW)
            })

            it('includes FORCE_OVERFLOW if any filter matches (OR logic)', async () => {
                await setupDynamicConfig(pipelineMock, eventIngestionRestrictionManager, {
                    forceOverflowTokens: ['token:distinct_id:user1', 'token:event_uuid:uuid-123'],
                })
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token', {
                        distinct_id: 'user1',
                        session_id: 'other-session',
                        uuid: 'other-uuid',
                    })
                ).toContain(Restriction.FORCE_OVERFLOW)
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token', {
                        distinct_id: 'other-user',
                        session_id: 'other-session',
                        uuid: 'uuid-123',
                    })
                ).toContain(Restriction.FORCE_OVERFLOW)
                expect(
                    eventIngestionRestrictionManager.getAppliedRestrictions('token', {
                        distinct_id: 'other-user',
                        session_id: 'other-session',
                        uuid: 'other-uuid',
                    })
                ).not.toContain(Restriction.FORCE_OVERFLOW)
            })
        })
    })

    describe('multiple restrictions for same entity', () => {
        it('returns multiple restrictions when token matches multiple static lists', async () => {
            eventIngestionRestrictionManager = new EventIngestionRestrictionManager(hub.redisPool, {
                staticDropEventTokens: ['multi-token'],
                staticSkipPersonTokens: ['multi-token'],
                staticForceOverflowTokens: ['multi-token'],
                staticRedirectToDlqTokens: ['multi-token'],
            })
            await eventIngestionRestrictionManager.forceRefresh()
            const restrictions = eventIngestionRestrictionManager.getAppliedRestrictions('multi-token')
            expect(restrictions).toContain(Restriction.DROP_EVENT)
            expect(restrictions).toContain(Restriction.SKIP_PERSON_PROCESSING)
            expect(restrictions).toContain(Restriction.FORCE_OVERFLOW)
            expect(restrictions).toContain(Restriction.REDIRECT_TO_DLQ)
            expect(restrictions.size).toBe(4)
        })

        it('returns multiple restrictions when token matches multiple dynamic config lists', async () => {
            await setupDynamicConfig(pipelineMock, eventIngestionRestrictionManager, {
                dropTokens: ['token'],
                skipPersonTokens: ['token'],
                forceOverflowTokens: ['token'],
                redirectToDlqTokens: ['token'],
            })
            const restrictions = eventIngestionRestrictionManager.getAppliedRestrictions('token')
            expect(restrictions).toContain(Restriction.DROP_EVENT)
            expect(restrictions).toContain(Restriction.SKIP_PERSON_PROCESSING)
            expect(restrictions).toContain(Restriction.FORCE_OVERFLOW)
            expect(restrictions).toContain(Restriction.REDIRECT_TO_DLQ)
            expect(restrictions.size).toBe(4)
        })

        it('returns DROP_EVENT and SKIP_PERSON_PROCESSING for token:distinct_id combination', async () => {
            await setupDynamicConfig(pipelineMock, eventIngestionRestrictionManager, {
                dropTokens: ['token:distinct_id:user1'],
                skipPersonTokens: ['token:distinct_id:user1'],
            })
            const restrictions = eventIngestionRestrictionManager.getAppliedRestrictions('token', {
                distinct_id: 'user1',
            })
            expect(restrictions).toContain(Restriction.DROP_EVENT)
            expect(restrictions).toContain(Restriction.SKIP_PERSON_PROCESSING)
            expect(restrictions).not.toContain(Restriction.FORCE_OVERFLOW)
            expect(restrictions).not.toContain(Restriction.REDIRECT_TO_DLQ)
            expect(restrictions.size).toBe(2)
        })

        it('returns FORCE_OVERFLOW and REDIRECT_TO_DLQ for session_id', async () => {
            await setupDynamicConfig(pipelineMock, eventIngestionRestrictionManager, {
                forceOverflowTokens: ['token:session_id:session123'],
                redirectToDlqTokens: ['token:session_id:session123'],
            })
            const restrictions = eventIngestionRestrictionManager.getAppliedRestrictions('token', {
                session_id: 'session123',
            })
            expect(restrictions).toContain(Restriction.FORCE_OVERFLOW)
            expect(restrictions).toContain(Restriction.REDIRECT_TO_DLQ)
            expect(restrictions).not.toContain(Restriction.DROP_EVENT)
            expect(restrictions).not.toContain(Restriction.SKIP_PERSON_PROCESSING)
            expect(restrictions.size).toBe(2)
        })

        it('combines static and dynamic restrictions', async () => {
            eventIngestionRestrictionManager = new EventIngestionRestrictionManager(hub.redisPool, {
                staticDropEventTokens: ['combo-token'],
                staticSkipPersonTokens: [],
                staticForceOverflowTokens: [],
                staticRedirectToDlqTokens: [],
            })
            await setupDynamicConfig(pipelineMock, eventIngestionRestrictionManager, {
                skipPersonTokens: ['combo-token'],
                forceOverflowTokens: ['combo-token'],
            })
            const restrictions = eventIngestionRestrictionManager.getAppliedRestrictions('combo-token')
            expect(restrictions).toContain(Restriction.DROP_EVENT)
            expect(restrictions).toContain(Restriction.SKIP_PERSON_PROCESSING)
            expect(restrictions).toContain(Restriction.FORCE_OVERFLOW)
            expect(restrictions).not.toContain(Restriction.REDIRECT_TO_DLQ)
            expect(restrictions.size).toBe(3)
        })

        it('matches different restriction types by different identifiers', async () => {
            await setupDynamicConfig(pipelineMock, eventIngestionRestrictionManager, {
                dropTokens: ['token:distinct_id:user1'],
                skipPersonTokens: ['token:session_id:session123'],
                forceOverflowTokens: ['token:event_name:$pageview'],
                redirectToDlqTokens: ['token:event_uuid:uuid-abc'],
            })
            const restrictions = eventIngestionRestrictionManager.getAppliedRestrictions('token', {
                distinct_id: 'user1',
                session_id: 'session123',
                event: '$pageview',
                uuid: 'uuid-abc',
            })
            expect(restrictions).toContain(Restriction.DROP_EVENT)
            expect(restrictions).toContain(Restriction.SKIP_PERSON_PROCESSING)
            expect(restrictions).toContain(Restriction.FORCE_OVERFLOW)
            expect(restrictions).toContain(Restriction.REDIRECT_TO_DLQ)
            expect(restrictions.size).toBe(4)
        })

        it('returns partial matches when only some identifiers match', async () => {
            await setupDynamicConfig(pipelineMock, eventIngestionRestrictionManager, {
                dropTokens: ['token:distinct_id:user1'],
                skipPersonTokens: ['token:session_id:other-session'],
                forceOverflowTokens: ['token:event_name:$pageview'],
                redirectToDlqTokens: ['token:event_uuid:other-uuid'],
            })
            const restrictions = eventIngestionRestrictionManager.getAppliedRestrictions('token', {
                distinct_id: 'user1',
                session_id: 'session123',
                event: '$pageview',
                uuid: 'uuid-abc',
            })
            expect(restrictions).toContain(Restriction.DROP_EVENT)
            expect(restrictions).not.toContain(Restriction.SKIP_PERSON_PROCESSING)
            expect(restrictions).toContain(Restriction.FORCE_OVERFLOW)
            expect(restrictions).not.toContain(Restriction.REDIRECT_TO_DLQ)
            expect(restrictions.size).toBe(2)
        })

        it('returns empty when no restrictions match despite having configs', async () => {
            await setupDynamicConfig(pipelineMock, eventIngestionRestrictionManager, {
                dropTokens: ['other-token'],
                skipPersonTokens: ['token:distinct_id:other-user'],
                forceOverflowTokens: ['token:session_id:other-session'],
                redirectToDlqTokens: ['token:event_name:other-event'],
            })
            const restrictions = eventIngestionRestrictionManager.getAppliedRestrictions('token', {
                distinct_id: 'user1',
                session_id: 'session123',
                event: '$pageview',
            })
            expect(restrictions.size).toBe(0)
        })

        it('token-level restriction applies regardless of other identifiers', async () => {
            await setupDynamicConfig(pipelineMock, eventIngestionRestrictionManager, {
                dropTokens: ['token'],
                skipPersonTokens: ['token'],
            })
            const restrictions = eventIngestionRestrictionManager.getAppliedRestrictions('token', {
                distinct_id: 'any-user',
                session_id: 'any-session',
                event: 'any-event',
                uuid: 'any-uuid',
            })
            expect(restrictions).toContain(Restriction.DROP_EVENT)
            expect(restrictions).toContain(Restriction.SKIP_PERSON_PROCESSING)
            expect(restrictions.size).toBe(2)
        })
    })
})
