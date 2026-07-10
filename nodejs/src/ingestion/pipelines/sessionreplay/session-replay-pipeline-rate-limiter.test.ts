/**
 * Executable spec for how the session rate limiter behaves under Redis failures.
 *
 * ## The two principles this suite enforces
 *
 *   1. RATE LIMITING IS BEST-EFFORT. On a failure it may UNDER-count a session (let it through
 *      un-limited) but must NEVER OVER-count (charge the same session twice). Rate-limiting ops fail
 *      open.
 *   2. ENCRYPTION KEY INTEGRITY IS NON-NEGOTIABLE. Anything that could record without a key (cleartext)
 *      or switch a session's key mid-stream must FAIL HARD — throw and let the retry re-run — never
 *      guess.
 *
 * These pull in opposite directions on the one signal that serves both — "has this session been seen?"
 * — which decides both whether to rate-limit AND whether to generate vs fetch the encryption key. Rule 2
 * is stricter, so it wins there. That gives the per-op policy this suite locks in:
 *
 *   | Redis op                     | drives                          | policy                        |
 *   |------------------------------|---------------------------------|-------------------------------|
 *   | tracker hasSeen (MGET)       | key generate-vs-fetch + count   | FAIL HARD (throw → retry)     |
 *   | tracker markSeen (pipeline)  | seen persistence (count only)   | fail open (under-count)       |
 *   | filter isBlocked (MGET)      | drop-if-blocked + skip-recharge | fail open (under-block)       |
 *   | filter blockSessions (pipe)  | block persistence (count only)  | fail open (under-block)       |
 *
 * ## What the tests do
 *
 * Unlike session-replay-pipeline.test.ts (which mocks the tracker/filter), this builds the REAL
 * SessionTracker and SessionFilter over an in-memory fake Redis we can fault-inject per operation, so it
 * exercises the actual fail-open / fail-hard logic. "Counted as new" means the session was passed to
 * SessionFilter.handleNewSessions (which consumes a rate-limit token). An allowed or deleted session is
 * counted exactly once — both are marked seen, so the next batch reads them as existing. A session
 * already on the blocklist is counted ZERO times: it's held out of the budget by its block key, not by
 * being marked seen, so it's excluded from the charge before handleNewSessions rather than re-charged
 * every batch. (A session freshly rate-limited in a batch is still counted the once, when it's blocked.)
 *
 * - baseline: every session type counted once.
 * - transient failure (fails once, recovers): counting is unaffected — a fail-open op is masked, a
 *   fail-hard op (hasSeen) is retried and recovers. Each test also asserts the fault actually fired.
 * - sustained outage (fails every batch): documents the degradation direction — hasSeen throws (fail
 *   hard, reprocess on recovery) while the fail-open ops keep flowing but under-enforce and don't persist.
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

type FaultSpec = { op: FakeRedisOp; keyPrefix: string } | null

/** Minimal in-memory Redis supporting the tracker/filter access patterns, with per-op fault injection. */
class FakeRedis {
    public store = new Map<string, string>()
    private failOnce: FaultSpec = null
    private failEvery: FaultSpec = null

    /** Make the next matching operation (touching a key with the given prefix) throw exactly once. */
    failNext(op: FakeRedisOp, keyPrefix: string): void {
        this.failOnce = { op, keyPrefix }
    }

    /** Make every matching operation throw — a sustained outage of that op, until cleared. */
    failAlways(op: FakeRedisOp, keyPrefix: string): void {
        this.failEvery = { op, keyPrefix }
    }

    /** True while an armed one-shot fault hasn't fired yet — lets tests assert the failure was exercised. */
    hasPendingFailure(): boolean {
        return this.failOnce !== null
    }

    private matches(spec: FaultSpec, op: FakeRedisOp, keys: string[]): boolean {
        return spec !== null && spec.op === op && keys.some((k) => k.startsWith(spec.keyPrefix))
    }

    private maybeFail(op: FakeRedisOp, keys: string[]): void {
        if (this.matches(this.failOnce, op, keys)) {
            this.failOnce = null
            throw new Error(`fake redis ${op} failed`)
        }
        if (this.matches(this.failEvery, op, keys)) {
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
    const team: TeamForReplay = {
        teamId: TEAM_ID,
        consoleLogIngestionEnabled: false,
        aiTrainingOptedIn: true,
        firstPartyHosts: [],
    }
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
            overflowMode: 'disabled',
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

    async function runBatch(sessionId: string, offset: number): Promise<void> {
        await runSessionReplayPipeline(buildPipeline(), [createMessage(sessionId, offset)], new PromiseScheduler())
    }

    // Assert a one-shot fault armed with failNext() actually fired — guards against a silently-inert fault
    // (wrong op/prefix) that would make a test pass without exercising the failure it claims to.
    const expectFaultFired = (): void => expect(redis.hasPendingFailure()).toBe(false)

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

    // A key is resolved only for sessions that pass the block check; a dropped (blocked) session skips it.
    const keyWasResolvedFor = (sessionId: string): boolean =>
        keyStore.generateKey.mock.calls.some((c) => c[0] === sessionId) ||
        keyStore.getKey.mock.calls.some((c) => c[0] === sessionId)

    const blockKey = (sessionId: string): string => `${BLOCK_PREFIX}:${TEAM_ID}:${sessionId}`
    const seenKey = (sessionId: string): string => `${SEEN_PREFIX}:${TEAM_ID}:${sessionId}`

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

    // Establishes the baseline (no Redis failures): allowed and deleted are counted once (both marked
    // seen at the mark-seen step, so batch two reads them as existing), while an already-blocklisted
    // session is counted zero times — its block key, not a seen flag, keeps it out of the budget.
    describe('baseline (no failures)', () => {
        it.each<[SessionType, number]>([
            ['allowed', 1],
            ['blocked', 0],
            ['deleted', 1],
        ])('%s session is counted as new %i time(s) over two batches', async (type, expected) => {
            setUpSessionType(type, type)

            await runBatch(type, 1)
            await runBatch(type, 2)

            expect(timesCountedAsNew(type)).toBe(expected)
        })
    })

    // hasSeen fails hard (throws), so the step's retry wrapper re-runs it — a transient blip recovers on
    // the retry and counting is unaffected (rather than guessing "seen" and risking a keyless recording).
    // Blocked stays 0 as in the baseline: recovery restores the block read, which excludes it from the charge.
    describe('when the hasSeen read (tracker MGET) fails once then recovers on retry', () => {
        it.each<[SessionType, number]>([
            ['allowed', 1],
            ['blocked', 0],
            ['deleted', 1],
        ])('%s session is counted as new %i time(s)', async (type, expected) => {
            setUpSessionType(type, type)

            // hasSeen is the MGET on the seen keys; make it throw once on the first batch.
            redis.failNext('mget', SEEN_PREFIX)
            await runBatch(type, 1)
            expectFaultFired()
            await runBatch(type, 2)

            expect(timesCountedAsNew(type)).toBe(expected)
        })
    })

    // markSeen fails open: the mark isn't persisted to Redis, but the local cache still records it, so
    // the SAME consumer doesn't re-count the session next batch (the failure is masked locally). Only
    // allowed and deleted are marked seen (a blocked session never is), so only those exercise this fault.
    describe('when the markSeen write (tracker pipeline) fails on the first batch', () => {
        it.each<[SessionType, number]>([
            ['allowed', 1],
            ['deleted', 1],
        ])('%s session is counted as new %i time(s)', async (type, expected) => {
            setUpSessionType(type, type)

            // markSeen is the pipeline EXEC on the seen keys; make it throw once on the first batch.
            redis.failNext('exec', SEEN_PREFIX)
            await runBatch(type, 1)
            expectFaultFired()
            await runBatch(type, 2)

            expect(timesCountedAsNew(type)).toBe(expected)
        })
    })

    // isBlocked fails open (assume not blocked). The block read now gates the charge, but failing open
    // means the already-blocked session is treated as unblocked: it leaks past the block for that batch,
    // so it's counted the once (then marked seen) instead of being excluded — the same single count the
    // other types get. Recovery on batch two reads it as existing, so it isn't re-counted.
    describe('when the isBlocked read (filter MGET) fails on the first batch', () => {
        it.each<[SessionType, number]>([
            ['allowed', 1],
            ['blocked', 1],
            ['deleted', 1],
        ])('%s session is counted as new %i time(s)', async (type, expected) => {
            setUpSessionType(type, type)

            // isBlocked is the MGET on the block keys; make it throw once on the first batch.
            redis.failNext('mget', BLOCK_PREFIX)
            await runBatch(type, 1)
            expectFaultFired()
            await runBatch(type, 2)

            expect(timesCountedAsNew(type)).toBe(expected)
        })
    })

    // blockSessions only runs when a new session is rate-limited (empty bucket). It fails open: the block
    // isn't persisted to Redis, but the local cache records it, so the session is still dropped and
    // marked seen on this consumer — counted once.
    describe('when the blockSessions write (filter pipeline) fails on the first batch', () => {
        it('a newly rate-limited session is counted once, dropped locally, but the block is not persisted', async () => {
            useBucketCapacity(0) // force the session to be rate-limited so blockSessions runs

            // blockSessions is the pipeline EXEC on the block keys; make it throw once on the first batch.
            redis.failNext('exec', BLOCK_PREFIX)
            await runBatch('rate-limited', 1)
            expectFaultFired()
            await runBatch('rate-limited', 2)

            expect(timesCountedAsNew('rate-limited')).toBe(1)
            // Fail-open write path: still blocked on this consumer (local cache → key never resolved) but
            // not durable in Redis.
            expect(keyWasResolvedFor('rate-limited')).toBe(false)
            expect(redis.store.has(blockKey('rate-limited'))).toBe(false)
        })
    })

    // Sustained outages: the op fails on EVERY batch, across many batches. Documents how the fail-open /
    // fail-safe defaults behave when Redis stays down — the direction each degrades in, and that it
    // doesn't drift over time.
    describe('sustained outage (op fails on every batch)', () => {
        const BATCHES = 6
        const runBatches = async (sessionId: string): Promise<void> => {
            for (let offset = 1; offset <= BATCHES; offset++) {
                await runBatch(sessionId, offset)
            }
        }

        it('hasSeen down: the batch fails hard (throws) rather than guessing — nothing is counted', async () => {
            redis.failAlways('mget', SEEN_PREFIX)
            setUpSessionType('allowed', 'a')

            // Fail-hard: retries exhaust and the batch throws. The error propagates out, so the offset is
            // never committed and the consumer crashes; Kafka reassigns the partition to another consumer
            // that hits the same failure — a crash/rebalance loop that keeps the batch uncommitted until
            // Redis recovers and it finally succeeds, rather than ever committing a keyless recording.
            // hasSeen runs before counting, so nothing is counted.
            await expect(runBatch('a', 1)).rejects.toThrow()
            expect(timesCountedAsNew('a')).toBe(0)
        })

        it('markSeen down: the mark never reaches Redis, but the local cache keeps counting at once', async () => {
            redis.failAlways('exec', SEEN_PREFIX)
            setUpSessionType('allowed', 'a')

            await runBatches('a')

            expect(timesCountedAsNew('a')).toBe(1)
            // Seen state is masked in the local cache only — nothing persisted for other consumers.
            expect(redis.store.has(seenKey('a'))).toBe(false)
        })

        it('isBlocked down: an already-blocked session leaks past the block every batch; counting once', async () => {
            redis.failAlways('mget', BLOCK_PREFIX)
            setUpSessionType('blocked', 'a') // pre-seeded block flag that isBlocked can no longer read

            await runBatches('a')

            // Assumed not-blocked → key resolved (heads to recording) instead of dropped; counted once.
            expect(keyWasResolvedFor('a')).toBe(true)
            expect(timesCountedAsNew('a')).toBe(1)
        })

        it('blockSessions down: rate-limited sessions are counted once but never durably blocked', async () => {
            useBucketCapacity(0)
            redis.failAlways('exec', BLOCK_PREFIX)

            await runBatches('rate-limited')

            expect(timesCountedAsNew('rate-limited')).toBe(1)
            expect(keyWasResolvedFor('rate-limited')).toBe(false)
            expect(redis.store.has(blockKey('rate-limited'))).toBe(false)
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
