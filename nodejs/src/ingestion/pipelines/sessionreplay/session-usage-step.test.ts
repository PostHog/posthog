import { UsageIngestionClient, UsageRecordInput } from '~/common/usage-ingestion/client'
import { UsageRecordBatch } from '~/common/usage-ingestion/usage-record-batch'

import { createRecordSessionUsageStep } from './session-usage-step'

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

    async function record(
        snapshotSource: string | null,
        snapshotLibrary: string | null,
        isNewSession = true
    ): Promise<string[]> {
        const step = createRecordSessionUsageStep(usageBatch)
        await step({
            team: { teamId: 42 },
            headers: { session_id: 'session-1' },
            parsedMessage: { snapshot_source: snapshotSource, snapshot_library: snapshotLibrary },
            isNewSession,
        } as any)

        await usageBatch.flush()
        return ingested.map((record) => record.usageKey)
    }

    it.each([
        ['web', 'posthog-js', ['session_replay_recordings']],
        [null, null, ['session_replay_recordings']],
        ['mobile', 'posthog-ios', ['mobile_replay_recordings']],
        ['mobile', 'posthog-flutter', ['mobile_replay_recordings']],
        // The report bills mobile replay only from its own SDKs, so anything else is neither meter.
        ['mobile', 'posthog-python', []],
        ['mobile', null, []],
    ])('bills a %s session from %s under %j', async (source, library, expectedUsageKeys) => {
        expect(await record(source, library)).toEqual(expectedUsageKeys)
    })

    it('bills nothing for a session already seen in this batch', async () => {
        expect(await record('web', 'posthog-js', false)).toEqual([])
    })
})
