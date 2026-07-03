/**
 * Characterization suite for the rate limiter's behavior under Redis failures.
 *
 * Unlike session-replay-pipeline.test.ts (which mocks the tracker/filter), this builds the real
 * SessionTracker and SessionFilter over an in-memory fake Redis we can fault-inject per operation, so we
 * exercise the actual fail-open/fail-safe logic. Each test drives the real pipeline for one session
 * across two batches — failing one Redis operation on the first batch, healthy on the second — and
 * documents, per session type (allowed / blocked / deleted), how many times the session is counted as
 * new (i.e. passed to SessionFilter.handleNewSessions, which consumes a rate-limit token).
 *
 * These assertions pin down CURRENT behavior. They are not a statement of desired behavior — we'll use
 * them to decide how each case should be handled.
 */
import { Redis } from 'ioredis'
import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'

import { DLQ_OUTPUT, INGESTION_WARNINGS_OUTPUT, OVERFLOW_OUTPUT } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { EventIngestionRestrictionManager } from '~/common/utils/event-ingestion-restrictions'
import { PromiseScheduler } from '~/common/utils/promise-scheduler'
import { createApplyEventRestrictionsStep, createParseHeadersStep } from '~/ingestion/common/steps/event-preprocessing'
import { TopHogRegistry } from '~/ingestion/framework/extensions/tophog'
import { ok } from '~/ingestion/framework/results'
import { SessionBatchManager } from '~/ingestion/pipelines/sessionreplay/sessions/session-batch-manager'
import { SessionBatchRecorder } from '~/ingestion/pipelines/sessionreplay/sessions/session-batch-recorder'
import { SessionFilter } from '~/ingestion/pipelines/sessionreplay/sessions/session-filter'
import { SessionTracker } from '~/ingestion/pipelines/sessionreplay/sessions/session-tracker'
import { RetentionService } from '~/ingestion/pipelines/sessionreplay/shared/retention/retention-service'
import { SessionMap, SessionSet } from '~/ingestion/pipelines/sessionreplay/shared/session-map'
import { TeamService } from '~/ingestion/pipelines/sessionreplay/shared/teams/team-service'
import { createMockSessionKey } from '~/ingestion/pipelines/sessionreplay/shared/test-helpers'
import { KeyStore } from '~/ingestion/pipelines/sessionreplay/shared/types'
import { TeamForReplay } from '~/ingestion/pipelines/sessionreplay/teams/types'
import { createMockIngestionOutputs } from '~/tests/helpers/mock-ingestion-outputs'
import { RedisPool } from '~/types'

import { createSessionReplayPipeline, runSessionReplayPipeline } from './session-replay-pipeline'

jest.mock('~/ingestion/common/steps/event-preprocessing', () => ({
    createParseHeadersStep: jest.fn(),
    createApplyEventRestrictionsStep: jest.fn(),
}))

const SEEN_PREFIX = '@posthog/replay/session-seen'
const BLOCK_PREFIX = '@posthog/replay/session-blocked'

type FakeRedisOp = 'mget' | 'exec'

/** Minimal in-memory Redis supporting the tracker/filter access patterns, with per-op fault injection. */
class FakeRedis {
    public store = new Map<string, string>()
    private failOnce: { op: FakeRedisOp; keyPrefix: string } | null = null

    /** Make the next matching operation (touching a key with the given prefix) throw exactly once. */
    failNext(op: FakeRedisOp, keyPrefix: string): void {
        this.failOnce = { op, keyPrefix }
    }

    private maybeFail(op: FakeRedisOp, keys: string[]): void {
        if (this.failOnce && this.failOnce.op === op && keys.some((k) => k.startsWith(this.failOnce!.keyPrefix))) {
            this.failOnce = null
            throw new Error(`fake redis ${op} failed`)
        }
    }

    mget(keys: string[]): Promise<(string | null)[]> {
        this.maybeFail('mget', keys)
        return Promise.resolve(keys.map((k) => this.store.get(k) ?? null))
    }

    pipeline(): FakePipeline {
        return new FakePipeline(this)
    }

    commit(sets: Array<[string, string]>): void {
        this.maybeFail(
            'exec',
            sets.map(([k]) => k)
        )
        for (const [k, v] of sets) {
            this.store.set(k, v)
        }
    }
}

class FakePipeline {
    private sets: Array<[string, string]> = []
    constructor(private redis: FakeRedis) {}
    set(key: string, val: string, ..._args: unknown[]): this {
        this.sets.push([key, val])
        return this
    }
    exec(): Promise<unknown> {
        this.redis.commit(this.sets)
        return Promise.resolve(this.sets.map(() => [null, 'OK']))
    }
}

function createMockSessionBatchManager(): jest.Mocked<SessionBatchManager> {
    const mockBatchRecorder = {
        record: jest.fn().mockResolvedValue(undefined),
        getRetention: jest.fn().mockReturnValue(undefined),
    } as unknown as jest.Mocked<SessionBatchRecorder>
    return {
        getCurrentBatch: jest.fn().mockReturnValue(mockBatchRecorder),
        shouldFlush: jest.fn().mockReturnValue(false),
        flush: jest.fn().mockResolvedValue(undefined),
        discardPartitions: jest.fn(),
    } as unknown as jest.Mocked<SessionBatchManager>
}

const mockCreateParseHeadersStep = createParseHeadersStep as jest.Mock
const mockCreateApplyEventRestrictionsStep = createApplyEventRestrictionsStep as jest.Mock

type SessionType = 'allowed' | 'blocked' | 'deleted'

describe('session-replay-pipeline rate limiter failure modes', () => {
    const TEAM_ID = 1
    const team: TeamForReplay = { teamId: TEAM_ID, consoleLogIngestionEnabled: false, aiTrainingOptedIn: true }
    const now = DateTime.fromMillis(1_700_000_000_000)

    let redis: FakeRedis
    let pool: RedisPool
    let sessionTracker: SessionTracker
    let sessionFilter: SessionFilter
    let keyStore: jest.Mocked<KeyStore>
    let sessionBatchManager: jest.Mocked<SessionBatchManager>
    let outputs: jest.Mocked<
        IngestionOutputs<typeof DLQ_OUTPUT | typeof OVERFLOW_OUTPUT | typeof INGESTION_WARNINGS_OUTPUT>
    >
    let countedSessions: string[]

    const keyPrefixOf = (op: 'hasSeen' | 'markSeen' | 'isBlocked' | 'blockSessions'): string =>
        op === 'hasSeen' || op === 'markSeen' ? SEEN_PREFIX : BLOCK_PREFIX
    const redisOpOf = (op: 'hasSeen' | 'markSeen' | 'isBlocked' | 'blockSessions'): FakeRedisOp =>
        op === 'hasSeen' || op === 'isBlocked' ? 'mget' : 'exec'

    // Rebuilds the real SessionFilter with a given bucket capacity (capacity 0 forces new sessions to be
    // rate-limited, which is the only way blockSessions is exercised), re-applying the counting spy.
    function useBucketCapacity(bucketCapacity: number): void {
        sessionFilter = new SessionFilter({
            redisPool: pool,
            bucketCapacity,
            bucketReplenishRate: bucketCapacity,
            blockingEnabled: true,
            filterEnabled: true,
            localCacheTtlMs: 5 * 60 * 1000,
        })
        applyCountingSpy()
    }

    function applyCountingSpy(): void {
        jest.spyOn(sessionFilter, 'handleNewSessions').mockImplementation((sessions: SessionSet) => {
            for (const { sessionId } of sessions) {
                countedSessions.push(sessionId)
            }
            // Call through to the real limiter so blocking still happens.
            return SessionFilter.prototype.handleNewSessions.call(sessionFilter, sessions)
        })
    }

    function buildPipeline() {
        const retentionService = {
            resolveSessionRetentions: jest.fn().mockImplementation((sessions: SessionSet) => {
                const resolutions = new SessionMap<{ resolved: true; retentionPeriod: '30d' }>()
                for (const { teamId, sessionId } of sessions) {
                    resolutions.set(teamId, sessionId, { resolved: true, retentionPeriod: '30d' })
                }
                return Promise.resolve(resolutions)
            }),
        } as unknown as RetentionService

        return createSessionReplayPipeline({
            outputs,
            eventIngestionRestrictionManager: {} as unknown as EventIngestionRestrictionManager,
            overflowEnabled: false,
            promiseScheduler: new PromiseScheduler(),
            teamService: {
                getTeamByToken: jest.fn().mockResolvedValue(team),
                getRetentionPeriodByTeamId: jest.fn().mockResolvedValue(30),
            } as unknown as TeamService,
            retentionService,
            sessionTracker,
            sessionFilter,
            keyStore,
            sessionKeyResolutionMaxConcurrency: 20,
            topHog: createMockTopHog(),
            sessionBatchManager,
            isDebugLoggingEnabled: () => false,
        })
    }

    function createMessage(sessionId: string, offset: number): Message {
        const event = {
            event: '$snapshot_items',
            properties: {
                $session_id: sessionId,
                $window_id: 'window-1',
                $snapshot_items: [
                    { type: 2, timestamp: now.toMillis(), data: {} },
                    { type: 3, timestamp: now.plus({ seconds: 1 }).toMillis(), data: {} },
                ],
            },
        }
        const payload = JSON.stringify({ distinct_id: 'user-123', data: JSON.stringify(event) })
        const headers = { token: 'test-token', session_id: sessionId, distinct_id: 'user-123' }
        return {
            partition: 0,
            offset,
            topic: 'test-topic',
            value: Buffer.from(payload),
            key: Buffer.from('test-key'),
            timestamp: now.toMillis(),
            headers: Object.entries(headers).map(([k, v]) => ({ [k]: Buffer.from(v) })),
            size: payload.length,
        } as Message
    }

    async function runBatch(
        sessionId: string,
        offset: number,
        fail?: 'hasSeen' | 'markSeen' | 'isBlocked' | 'blockSessions'
    ): Promise<void> {
        if (fail) {
            redis.failNext(redisOpOf(fail), keyPrefixOf(fail))
        }
        await runSessionReplayPipeline(buildPipeline(), [createMessage(sessionId, offset)])
    }

    function setUpSessionType(type: SessionType, sessionId: string): void {
        if (type === 'blocked') {
            // Pre-seed the persisted block flag so the session reads as already blocked.
            redis.store.set(`${BLOCK_PREFIX}:${TEAM_ID}:${sessionId}`, '1')
        }
        if (type === 'deleted') {
            keyStore.generateKey.mockResolvedValue(createMockSessionKey({ sessionState: 'deleted', deletedAt: 1 }))
            keyStore.getKey.mockResolvedValue(createMockSessionKey({ sessionState: 'deleted', deletedAt: 1 }))
        }
    }

    const timesCountedAsNew = (sessionId: string): number => countedSessions.filter((s) => s === sessionId).length

    beforeEach(() => {
        jest.clearAllMocks()
        redis = new FakeRedis()
        pool = {
            acquire: () => Promise.resolve(redis as unknown as Redis),
            release: () => Promise.resolve(),
        } as unknown as RedisPool
        sessionTracker = new SessionTracker(pool, 5 * 60 * 1000)
        sessionFilter = new SessionFilter({
            redisPool: pool,
            bucketCapacity: 1000,
            bucketReplenishRate: 1000,
            blockingEnabled: true,
            filterEnabled: true,
            localCacheTtlMs: 5 * 60 * 1000,
        })
        keyStore = {
            start: jest.fn().mockResolvedValue(undefined),
            generateKey: jest.fn().mockResolvedValue(createMockSessionKey()),
            getKey: jest.fn().mockResolvedValue(createMockSessionKey()),
            deleteKey: jest.fn(),
            stop: jest.fn(),
        } as unknown as jest.Mocked<KeyStore>
        sessionBatchManager = createMockSessionBatchManager()
        outputs = createMockIngestionOutputs()

        countedSessions = []
        applyCountingSpy()

        mockCreateParseHeadersStep.mockReturnValue((input: { message: Message; headers?: Record<string, string> }) => {
            const headers: Record<string, string> = {}
            for (const header of input.message.headers || []) {
                for (const [key, value] of Object.entries(header)) {
                    headers[key] = Buffer.isBuffer(value) ? value.toString() : (value as string)
                }
            }
            return Promise.resolve(ok({ ...input, headers }))
        })
        mockCreateApplyEventRestrictionsStep.mockReturnValue((input: unknown) => Promise.resolve(ok(input)))
    })

    // Establishes the baseline (no Redis failures): every session type is counted as new exactly once,
    // because allowed, blocked and deleted sessions are all marked seen at the mark-seen step.
    describe('baseline (no failures)', () => {
        it.each<[SessionType, number]>([
            ['allowed', 1],
            ['blocked', 1],
            ['deleted', 1],
        ])('%s session is counted as new %i time(s) over two batches', async (type, expected) => {
            setUpSessionType(type, type)

            await runBatch(type, 1)
            await runBatch(type, 2)

            expect(timesCountedAsNew(type)).toBe(expected)
        })
    })

    // hasSeen fails safe (assume seen), so every session in that batch is treated as existing and none
    // are counted as new — rate limiting is effectively skipped for that batch.
    describe('when the hasSeen read (tracker MGET) fails on the first batch', () => {
        it.each<[SessionType, number]>([
            ['allowed', 1],
            ['blocked', 1],
            ['deleted', 1],
        ])('%s session is counted as new %i time(s)', async (type, expected) => {
            setUpSessionType(type, type)

            await runBatch(type, 1, 'hasSeen')
            await runBatch(type, 2)

            expect(timesCountedAsNew(type)).toBe(expected)
        })
    })

    // markSeen fails open: the mark isn't persisted to Redis, but the local cache still records it, so
    // the SAME consumer doesn't re-count the session next batch (the failure is masked locally). Applies
    // to every type, since allowed, blocked and deleted are all marked here.
    describe('when the markSeen write (tracker pipeline) fails on the first batch', () => {
        it.each<[SessionType, number]>([
            ['allowed', 1],
            ['blocked', 1],
            ['deleted', 1],
        ])('%s session is counted as new %i time(s)', async (type, expected) => {
            setUpSessionType(type, type)

            await runBatch(type, 1, 'markSeen')
            await runBatch(type, 2)

            expect(timesCountedAsNew(type)).toBe(expected)
        })
    })

    // isBlocked fails open (assume not blocked). Counting happens before the block check, so it's
    // unaffected — the visible effect is that an already-blocked session isn't dropped that batch.
    describe('when the isBlocked read (filter MGET) fails on the first batch', () => {
        it.each<[SessionType, number]>([
            ['allowed', 1],
            ['blocked', 1],
            ['deleted', 1],
        ])('%s session is counted as new %i time(s)', async (type, expected) => {
            setUpSessionType(type, type)

            await runBatch(type, 1, 'isBlocked')
            await runBatch(type, 2)

            expect(timesCountedAsNew(type)).toBe(expected)
        })
    })

    // blockSessions only runs when a new session is rate-limited (empty bucket). It fails open: the block
    // isn't persisted to Redis, but the local cache records it, so the session is still dropped and
    // marked seen on this consumer — counted once.
    describe('when the blockSessions write (filter pipeline) fails on the first batch', () => {
        it('a newly rate-limited session is counted as new 1 time', async () => {
            useBucketCapacity(0) // force the session to be rate-limited so blockSessions runs

            await runBatch('rate-limited', 1, 'blockSessions')
            await runBatch('rate-limited', 2)

            expect(timesCountedAsNew('rate-limited')).toBe(1)
        })
    })
})

interface MockRecorder {
    record: jest.Mock
}

function createMockTopHog(): TopHogRegistry {
    const make = () => new Map<string, MockRecorder>()
    const sumRecorders = make()
    const maxRecorders = make()
    const averageRecorders = make()
    return {
        registerSum: jest.fn().mockImplementation((name: string) => {
            const recorder = { record: jest.fn() }
            sumRecorders.set(name, recorder)
            return recorder
        }),
        registerMax: jest.fn().mockImplementation((name: string) => {
            const recorder = { record: jest.fn() }
            maxRecorders.set(name, recorder)
            return recorder
        }),
        registerAverage: jest.fn().mockImplementation((name: string) => {
            const recorder = { record: jest.fn() }
            averageRecorders.set(name, recorder)
            return recorder
        }),
    } as unknown as TopHogRegistry
}
