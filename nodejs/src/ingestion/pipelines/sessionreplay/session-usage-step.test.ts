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
    // 'stored' is a send that the service kept while the client saw it fail.
    let sendFailure: 'none' | 'lost' | 'stored'

    function newUsageBatch(): UsageRecordBatch {
        const client = {
            ingest: jest.fn((records: UsageRecordInput[]) => {
                if (sendFailure !== 'lost') {
                    ingested.push(...records)
                }
                return Promise.resolve(sendFailure === 'none' ? records : [])
            }),
        } as unknown as UsageIngestionClient
        return new UsageRecordBatch(client, { unit: 'recordings', isTeamEnabled: () => true })
    }

    beforeEach(() => {
        ingested = []
        sendFailure = 'none'
        usageBatch = newUsageBatch()
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
        const seenKey = '@posthog/replay/session-seen:42:session-1'
        const billedKey = '@posthog/replay/session-billed:42:session-1'

        let redisValues: Map<string, string>
        let redisTtls: Map<string, number>
        let redisAvailable: boolean
        let redisPool: RedisPool

        beforeEach(() => {
            redisValues = new Map()
            redisTtls = new Map()
            redisAvailable = true
            const client = {
                pipeline: () => {
                    const commands: (() => string | null)[] = []
                    const pipeline = {
                        set: (key: string, value: string, _mode: string, ttlSeconds: number, condition?: string) => {
                            commands.push(() => {
                                if (condition === 'NX' && redisValues.has(key)) {
                                    return null
                                }
                                redisValues.set(key, value)
                                redisTtls.set(key, ttlSeconds)
                                return 'OK'
                            })
                            return pipeline
                        },
                        get: (key: string) => {
                            commands.push(() => redisValues.get(key) ?? null)
                            return pipeline
                        },
                        exec: () =>
                            redisAvailable
                                ? Promise.resolve(commands.map((command) => [null, command()]))
                                : Promise.reject(new Error('Redis unavailable')),
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

        it.each([
            ['loses', 'lost', 1],
            ['stores', 'stored', 2],
        ] as const)(
            'bills a failed send on the next saved flush with the first flush time when the service %s it',
            async (_name, failure, records) => {
                sendFailure = failure
                await flush([metadata('web', FIRST_FLUSH)])
                sendFailure = 'none'
                await flush([metadata('web', SECOND_FLUSH)])

                expect(ingested).toEqual(
                    Array(records).fill(expect.objectContaining({ recordId: 'session-1', timestampMs: FIRST_FLUSH }))
                )
            }
        )

        it('sends one billing time when two consumers bill a session at once', async () => {
            await Promise.all([
                flush([metadata('web', FIRST_FLUSH)]),
                billPersistedSessions(newUsageBatch(), new SessionTracker(redisPool, 60_000), [
                    metadata('web', SECOND_FLUSH),
                ]),
            ])

            expect(new Set(ingested.map((record) => record.timestampMs))).toEqual(new Set([FIRST_FLUSH]))
        })

        it('bills a session saved in only one flush when Redis is unavailable', async () => {
            redisAvailable = false
            await flush([metadata('web', FIRST_FLUSH)])

            expect(ingested).toEqual([expect.objectContaining({ recordId: 'session-1', timestampMs: FIRST_FLUSH })])
        })

        it.each([
            ['a session the tracker marked seen but did not bill', 'seen', ['session-1']],
            ['nothing for a session that an earlier release billed when it first saw it', '1', []],
        ])('bills %s', async (_name, trackerValue, billedSessionIds) => {
            redisValues.set(seenKey, trackerValue)

            await flush([metadata('web', FIRST_FLUSH)])

            expect(ingested.map((record) => record.recordId)).toEqual(billedSessionIds)
        })

        it.each([
            ['mobile', 7 * 24 * 60 * 60],
            ['web', 48 * 60 * 60],
        ])(
            'keeps a billed %s session marked for %i seconds without changing its seen key',
            async (source, ttlSeconds) => {
                redisValues.set(seenKey, 'seen')
                redisTtls.set(seenKey, 48 * 60 * 60)

                await flush([metadata(source, FIRST_FLUSH)])

                expect(redisTtls.get(billedKey)).toBe(ttlSeconds)
                expect([redisValues.get(seenKey), redisTtls.get(seenKey)]).toEqual(['seen', 48 * 60 * 60])
            }
        )
    })
})
