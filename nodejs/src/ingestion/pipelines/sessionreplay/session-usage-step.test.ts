import { DateTime } from 'luxon'
import { register } from 'prom-client'

import { UsageIngestionClient, UsageRecordInput } from '~/common/usage-ingestion/client'
import { UsageRecordBatch } from '~/common/usage-ingestion/usage-record-batch'
import { drop, ok } from '~/ingestion/framework/results'

import { ParsedMessageData } from './kafka/types'
import { Recordable, SessionReplayHeaders } from './pipeline-types'
import { createRecordSessionUsageStep, trackUnbilledNewSessions } from './session-usage-step'
import { TeamForReplay } from './teams/types'

type SessionUsageValue = Recordable<{
    team: TeamForReplay
    headers: SessionReplayHeaders
    parsedMessage: ParsedMessageData
    isNewSession: boolean
}>

describe('createRecordSessionUsageStep', () => {
    let ingested: UsageRecordInput[]
    let usageBatch: UsageRecordBatch

    beforeEach(() => {
        ingested = []
        const client = {
            ingest: jest.fn((records: UsageRecordInput[]) => {
                ingested.push(...records)
                return Promise.resolve()
            }),
        } as unknown as UsageIngestionClient
        usageBatch = new UsageRecordBatch(client, { unit: 'recordings', isTeamEnabled: () => true })
    })

    function buildValue(
        snapshotSource: string | null,
        snapshotLibrary: string | null,
        isNewSession: boolean
    ): SessionUsageValue {
        return {
            team: { teamId: 42, consoleLogIngestionEnabled: false, aiTrainingOptedIn: false },
            headers: { token: 'token', session_id: 'session-1', distinct_id: 'distinct-1' },
            parsedMessage: {
                distinct_id: 'distinct-1',
                session_id: 'session-1',
                token: 'token',
                eventsByWindowId: { window1: [] },
                eventsRange: { start: DateTime.fromMillis(0), end: DateTime.fromMillis(0) },
                snapshot_source: snapshotSource,
                snapshot_library: snapshotLibrary,
                metadata: { partition: 0, topic: 'test-topic', rawSize: 0, offset: 0, timestamp: 0 },
            },
            isNewSession,
            status: 'allowed',
            sessionKey: {
                plaintextKey: Buffer.alloc(0),
                encryptedKey: Buffer.alloc(0),
                sessionState: 'ciphertext',
            },
        }
    }

    async function record(
        snapshotSource: string | null,
        snapshotLibrary: string | null,
        isNewSession = true
    ): Promise<string[]> {
        const step = createRecordSessionUsageStep(usageBatch)
        await step(buildValue(snapshotSource, snapshotLibrary, isNewSession))

        await usageBatch.flush()
        return ingested.map((record) => record.usageKey)
    }

    it.each([
        ['web', 'posthog-js', ['session_replay_recordings']],
        ['mobile', 'posthog-ios', ['mobile_replay_recordings']],
        ['mobile', 'posthog-flutter', ['mobile_replay_recordings']],
        // The report bills mobile replay only from four named libraries. The meter reads the
        // source instead, so a mobile recording bills whatever library it names.
        ['mobile', 'posthog-python', ['mobile_replay_recordings']],
        ['mobile', null, ['mobile_replay_recordings']],
        // Nothing validates the source, so anything but 'mobile' bills as web rather than for free.
        ['desktop', 'posthog-js', ['session_replay_recordings']],
        [null, null, ['session_replay_recordings']],
    ])('bills a %s session from %s under %j', async (source, library, expectedUsageKeys) => {
        expect(await record(source, library)).toEqual(expectedUsageKeys)
    })

    it('bills nothing for a session already seen in this batch', async () => {
        expect(await record('web', 'posthog-js', false)).toEqual([])
    })

    describe('trackUnbilledNewSessions', () => {
        async function unbilledCount(): Promise<number> {
            const metric = register.getSingleMetric('recording_blob_ingestion_v2_unbilled_new_session')!
            const data = (await metric.get()) as { values: { value: number }[] }
            return data.values.reduce((total, entry) => total + entry.value, 0)
        }

        it.each([
            ['counts a new session whose message fails', true, false, 1],
            ['counts nothing for a session already seen', false, false, 0],
            ['counts nothing for a new session that parses', true, true, 0],
        ])('%s', async (_name, isNewSession, succeeds, expectedIncrease) => {
            const value = buildValue('web', 'posthog-js', isNewSession)
            const before = await unbilledCount()
            const step = trackUnbilledNewSessions(() =>
                Promise.resolve(succeeds ? ok(value) : drop<typeof value>('message_contained_no_valid_rrweb_events'))
            )

            await step(value)

            expect(await unbilledCount()).toEqual(before + expectedIncrease)
        })
    })
})
