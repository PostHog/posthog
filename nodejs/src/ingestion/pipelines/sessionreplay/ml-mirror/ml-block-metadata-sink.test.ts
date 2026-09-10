import { DateTime } from 'luxon'

import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { parseJSON } from '~/common/utils/json-parse'
import {
    SessionBlockMetadata,
    createNoopBlockMetadata,
} from '~/ingestion/pipelines/sessionreplay/shared/metadata/session-block-metadata'
import { ML_BLOCK_METADATA_OUTPUT, MlBlockMetadataOutput } from '~/ingestion/pipelines/sessionreplay/shared/outputs'

import { MlBlockMetadataSink } from './ml-block-metadata-sink'

const block = (sessionId: string, teamId: number, over: Partial<SessionBlockMetadata> = {}): SessionBlockMetadata => ({
    ...createNoopBlockMetadata(sessionId, teamId),
    distinctId: 'user@example.com',
    blockUrl: `s3://ml-bucket/key-${sessionId}?range=bytes=0-9`,
    startDateTime: DateTime.fromMillis(1_000),
    endDateTime: DateTime.fromMillis(2_000),
    eventCount: 4,
    urls: ['https://x/[redacted]'],
    ...over,
})

describe('MlBlockMetadataSink', () => {
    let outputs: jest.Mocked<IngestionOutputs<MlBlockMetadataOutput>>
    let sink: MlBlockMetadataSink

    beforeEach(() => {
        outputs = { queueMessages: jest.fn().mockResolvedValue(undefined) } as unknown as jest.Mocked<
            IngestionOutputs<MlBlockMetadataOutput>
        >
        sink = new MlBlockMetadataSink(outputs, 'test-secret')
    })

    it('produces raw IDs to the ML topic, keyed by the session ID', async () => {
        await sink.storeSessionBlocks([block('01a0901f-d380-7000-8000-000000000001', 7)])

        expect(outputs.queueMessages).toHaveBeenCalledTimes(1)
        const [output, messages] = outputs.queueMessages.mock.calls[0]
        expect(output).toBe(ML_BLOCK_METADATA_OUTPUT)
        expect(messages[0].key).toBe('01a0901f-d380-7000-8000-000000000001')

        const row = parseJSON((messages[0].value as Buffer).toString())
        expect(row.session_id).toBe('01a0901f-d380-7000-8000-000000000001')
        expect(row.team_id).toBe('7')
        expect(row.distinct_id).toBe('user@example.com')
        expect(row.block_byte_end).toBe(9)
    })

    it('skips deletion and url-less markers', async () => {
        await sink.storeSessionBlocks([
            block('01a0901f-d380-7000-8000-000000000001', 1),
            block('s2', 1, { isDeleted: true }),
            block('s3', 1, { blockUrl: null }),
        ])
        const [, messages] = outputs.queueMessages.mock.calls[0]
        expect(messages).toHaveLength(1)
    })

    it('still calls queueMessages for an all-skipped batch', async () => {
        await sink.storeSessionBlocks([block('01a0901f-d380-7000-8000-000000000001', 1, { isDeleted: true })])
        expect(outputs.queueMessages).toHaveBeenCalledWith(ML_BLOCK_METADATA_OUTPUT, [])
    })
})
