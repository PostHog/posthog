import { UsageIngestionClient, UsageRecordInput } from '~/common/usage-ingestion/client'
import { UsageRecordBatch } from '~/common/usage-ingestion/usage-record-batch'
import { SessionTracker } from '~/ingestion/pipelines/sessionreplay/sessions/session-tracker'
import {
    SessionBlockMetadata,
    createNoopBlockMetadata,
} from '~/ingestion/pipelines/sessionreplay/shared/metadata/session-block-metadata'
import { RedisPool } from '~/types'

import { billPersistedSessions, recordPersistedSessionUsage } from './session-usage-step'

describe('session usage', () => {
    let ingested: UsageRecordInput[]
    let usageBatch: UsageRecordBatch
    let sendFails: boolean

    beforeEach(() => {
        ingested = []
        sendFails = false
        const client = {
            ingest: jest.fn((records: UsageRecordInput[]) => {
                if (sendFails) {
                    return Promise.resolve([])
                }
                ingested.push(...records)
                return Promise.resolve(records)
            }),
        } as unknown as UsageIngestionClient
        usageBatch = new UsageRecordBatch(client, { unit: 'recordings', isTeamEnabled: () => true })
    })

    function metadata(snapshotSource: string | null, captureTimestampMs?: number): SessionBlockMetadata {
        return {
            ...createNoopBlockMetadata('session-1', 42),
            snapshotSource,
            captureTimestampMs,
        }
    }

    async function record(sessions: SessionBlockMetadata[]): Promise<string[]> {
        recordPersistedSessionUsage(usageBatch, sessions)
        await usageBatch.flush()
        return ingested.map((record) => record.usageKey)
    }

    it.each([
        ['web', ['session_replay_recordings']],
        ['mobile', ['mobile_replay_recordings']],
        ['desktop', ['session_replay_recordings']],
        [null, ['session_replay_recordings']],
    ])('bills persisted %s metadata under %j', async (source, expectedUsageKeys) => {
        expect(await record([metadata(source, 1_700_000_000_000)])).toEqual(expectedUsageKeys)
    })

    it('uses the persisted session identity and trusted capture timestamp once', async () => {
        const persisted = metadata('web', 1_700_000_000_000)

        await record([persisted, persisted])

        expect(ingested).toEqual([
            expect.objectContaining({
                recordId: 'session-1',
                quantity: 1,
                timestampMs: 1_700_000_000_000,
            }),
        ])
    })

    it('bills nothing without persisted replay metadata', async () => {
        expect(await record([])).toEqual([])
    })

    describe('billing each saved session once', () => {
        const FIRST_FLUSH = Date.parse('2026-10-15T23:59:58Z')
        const SECOND_FLUSH = Date.parse('2026-10-16T00:00:03Z')
        const sessionKey = '@posthog/replay/session-seen:42:session-1'

        let redisValues: Map<string, string>
        let redisTtls: Map<string, number>
        let redisAvailable: boolean
        let redisPool: RedisPool

        beforeEach(() => {
            redisValues = new Map()
            redisTtls = new Map()
            redisAvailable = true
            const client = {
                mget: (keys: string[]) =>
                    redisAvailable
                        ? Promise.resolve(keys.map((key) => redisValues.get(key) ?? null))
                        : Promise.reject(new Error('Redis unavailable')),
                pipeline: () => {
                    const writes: [string, string, number][] = []
                    const pipeline = {
                        set: (key: string, value: string, _mode: string, ttlSeconds: number) => {
                            writes.push([key, value, ttlSeconds])
                            return pipeline
                        },
                        exec: () => {
                            for (const [key, value, ttlSeconds] of writes) {
                                redisValues.set(key, value)
                                redisTtls.set(key, ttlSeconds)
                            }
                            return Promise.resolve([])
                        },
                    }
                    return pipeline
                },
            }
            redisPool = {
                acquire: () => Promise.resolve(client),
                release: () => Promise.resolve(),
            } as unknown as RedisPool
        })

        // A new tracker for each flush, so the local cache cannot hide what Redis holds.
        async function flush(sessions: SessionBlockMetadata[]): Promise<void> {
            await billPersistedSessions(usageBatch, new SessionTracker(redisPool, 60_000), sessions)
        }

        it('bills a session saved in two flushes once, across midnight', async () => {
            await flush([metadata('web', FIRST_FLUSH)])
            await flush([metadata('web', SECOND_FLUSH)])

            expect(ingested).toEqual([expect.objectContaining({ recordId: 'session-1', timestampMs: FIRST_FLUSH })])
        })

        it.each<[string, () => void]>([
            ['the usage send fails', () => (sendFails = true)],
            ['Redis is unavailable', () => (redisAvailable = false)],
        ])('bills on the next saved flush when %s', async (_name, breakFirstFlush) => {
            breakFirstFlush()
            await flush([metadata('web', FIRST_FLUSH)])
            sendFails = false
            redisAvailable = true
            await flush([metadata('web', SECOND_FLUSH)])

            expect(ingested).toEqual([expect.objectContaining({ recordId: 'session-1', timestampMs: SECOND_FLUSH })])
        })

        it.each([
            ['a session the tracker marked seen but did not bill', 'seen', ['session-1']],
            ['nothing for a session that an earlier release billed when it first saw it', '1', []],
        ])('bills %s', async (_name, trackerValue, billedSessionIds) => {
            redisValues.set(sessionKey, trackerValue)

            await flush([metadata('web', FIRST_FLUSH)])

            expect(ingested.map((record) => record.recordId)).toEqual(billedSessionIds)
        })

        it.each([
            ['mobile', 7 * 24 * 60 * 60],
            ['web', 48 * 60 * 60],
        ])('keeps a billed %s session tracked for %i seconds', async (source, ttlSeconds) => {
            await flush([metadata(source, FIRST_FLUSH)])

            expect(redisTtls.get(sessionKey)).toBe(ttlSeconds)
        })
    })
})
