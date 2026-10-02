import { UsageIngestionClient, UsageRecordInput } from '~/common/usage-ingestion/client'
import { UsageRecordBatch } from '~/common/usage-ingestion/usage-record-batch'
import {
    SessionBlockMetadata,
    createNoopBlockMetadata,
} from '~/ingestion/pipelines/sessionreplay/shared/metadata/session-block-metadata'

import { recordPersistedSessionUsage } from './session-usage-step'

describe('session usage', () => {
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
})
