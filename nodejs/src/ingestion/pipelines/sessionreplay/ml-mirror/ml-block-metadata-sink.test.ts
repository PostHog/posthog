import { DateTime } from 'luxon'

import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { parseJSON } from '~/common/utils/json-parse'
import {
    SessionBlockMetadata,
    createNoopBlockMetadata,
} from '~/ingestion/pipelines/sessionreplay/shared/metadata/session-block-metadata'
import { ML_BLOCK_METADATA_OUTPUT, MlBlockMetadataOutput } from '~/ingestion/pipelines/sessionreplay/shared/outputs'

import { MlBlockMetadataSink } from './ml-block-metadata-sink'
import { PSEUDONYM_SESSION, pseudonymize } from './pseudonymize'

const SECRET = 'test-secret'

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
        sink = new MlBlockMetadataSink(outputs, SECRET)
    })

    it('produces pseudonymized rows to the ML topic, keyed by the session pseudonym', async () => {
        await sink.storeSessionBlocks([block('s1', 7)])

        expect(outputs.queueMessages).toHaveBeenCalledTimes(1)
        const [output, messages] = outputs.queueMessages.mock.calls[0]
        expect(output).toBe(ML_BLOCK_METADATA_OUTPUT)
        expect(messages[0].key).toBe(pseudonymize(SECRET, PSEUDONYM_SESSION, 's1'))

        const row = parseJSON((messages[0].value as Buffer).toString())
        expect(row.session_id).toBe(pseudonymize(SECRET, PSEUDONYM_SESSION, 's1'))
        expect(row.session_id).not.toBe('s1')
        expect(row.distinct_id).not.toContain('user@example.com')
        expect(row.block_byte_end).toBe(9)
    })

    it('skips deletion and url-less markers', async () => {
        await sink.storeSessionBlocks([
            block('s1', 1),
            block('s2', 1, { isDeleted: true }),
            block('s3', 1, { blockUrl: null }),
        ])
        const [, messages] = outputs.queueMessages.mock.calls[0]
        expect(messages).toHaveLength(1)
    })

    it('still calls queueMessages for an all-skipped batch', async () => {
        await sink.storeSessionBlocks([block('s1', 1, { isDeleted: true })])
        expect(outputs.queueMessages).toHaveBeenCalledWith(ML_BLOCK_METADATA_OUTPUT, [])
    })
})
