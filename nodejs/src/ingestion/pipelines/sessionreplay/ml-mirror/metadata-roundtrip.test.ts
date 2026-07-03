import { PutObjectCommandInput, S3Client } from '@aws-sdk/client-s3'
import { ParquetReader } from '@dsnp/parquetjs'
import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'

import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import {
    SessionBlockMetadata,
    createNoopBlockMetadata,
} from '~/ingestion/pipelines/sessionreplay/shared/metadata/session-block-metadata'
import { MlBlockMetadataOutput } from '~/ingestion/pipelines/sessionreplay/shared/outputs'

import { BlockMetadataBatcher, OffsetStore } from './block-metadata-batcher'
import { BlockMetadataParquetStore } from './block-metadata-parquet-store'
import { MlBlockMetadataSink } from './ml-block-metadata-sink'
import { PSEUDONYM_DISTINCT_ID, PSEUDONYM_SESSION, PSEUDONYM_TEAM, pseudonymize } from './pseudonymize'

const SECRET = 'roundtrip-secret'

const block = (sessionId: string, teamId: number, distinctId: string): SessionBlockMetadata => ({
    ...createNoopBlockMetadata(sessionId, teamId),
    distinctId,
    blockUrl: `s3://ml-bucket/key-${sessionId}?range=bytes=10-42`,
    startDateTime: DateTime.fromMillis(1_700_000_000_000),
    endDateTime: DateTime.fromMillis(1_700_000_005_000),
    eventCount: 5,
    messageCount: 2,
    clickCount: 1,
    urls: ['https://example.com/[redacted]'],
    snapshotSource: 'web',
})

async function readRows(body: PutObjectCommandInput['Body']): Promise<Record<string, any>[]> {
    const reader = await ParquetReader.openBuffer(body as Buffer)
    const cursor = reader.getCursor()
    const rows: Record<string, any>[] = []
    let row: unknown
    while ((row = await cursor.next())) {
        rows.push(row as Record<string, any>)
    }
    await reader.close()
    return rows
}

// End-to-end across both new deployments' metadata path: the mirror's producer serializes block metadata to the
// Kafka topic, and the sink's parser → batcher → Parquet store turns those exact bytes into an object in the ML bucket.
describe('ML metadata producer → sink round-trip', () => {
    it('pseudonymizes on the way out and recovers the same rows from the written Parquet', async () => {
        // --- Mirror (producer) side: block metadata → Kafka message bytes ---
        const produced: { key?: unknown; value: Buffer | null }[] = []
        const outputs = {
            queueMessages: jest.fn((_output, messages) => {
                produced.push(...messages)
                return Promise.resolve()
            }),
        } as unknown as IngestionOutputs<MlBlockMetadataOutput>

        await new MlBlockMetadataSink(outputs, SECRET).storeSessionBlocks([
            block('sess-A', 1, 'person-1'),
            block('sess-B', 2, 'person-2'),
        ])
        expect(produced).toHaveLength(2)

        // --- Sink (consumer) side: those exact bytes → parser → batcher → Parquet in S3 ---
        const puts: PutObjectCommandInput[] = []
        const s3 = {
            send: jest.fn((cmd: { input: PutObjectCommandInput }) => {
                puts.push(cmd.input)
                return Promise.resolve({})
            }),
        } as unknown as S3Client
        const store = new BlockMetadataParquetStore(s3, 'ml-bucket', 'block-metadata', 'pod-1')
        const offsetStore: OffsetStore = { offsetsStore: jest.fn() }
        const batcher = new BlockMetadataBatcher(store, offsetStore, { flushIntervalMs: 60_000, maxRows: 1_000 }, 0)

        const messages = produced.map(
            (m, i) => ({ topic: 'ml_block_metadata', partition: 0, offset: i, value: m.value }) as Message
        )
        await batcher.handleBatch(messages, 0)
        await batcher.flush(1) // force the window out

        expect(puts).toHaveLength(1)
        const rows = await readRows(puts[0].Body)
        expect(rows).toHaveLength(2)

        const bySession = new Map(rows.map((r) => [r.session_id, r]))
        const a = bySession.get(pseudonymize(SECRET, PSEUDONYM_SESSION, 'sess-A'))!
        expect(a).toBeDefined()
        expect(a.team_id).toBe(pseudonymize(SECRET, PSEUDONYM_TEAM, '1'))
        expect(a.distinct_id).toBe(pseudonymize(SECRET, PSEUDONYM_DISTINCT_ID, 'person-1'))
        // Raw ids never survive the trip (BigInt-safe stringify, since INT64 fields read back as bigint).
        expect(a.session_id).not.toBe('sess-A')
        const serialized = JSON.stringify(a, (_key, value) => (typeof value === 'bigint' ? value.toString() : value))
        expect(serialized).not.toContain('person-1')
        // Real block fields round-trip through JSON → Parquet → read.
        expect(Number(a.block_byte_start)).toBe(10)
        expect(Number(a.block_byte_end)).toBe(42)
        expect(a.event_count).toBe(5)
        expect(a.urls).toEqual(['https://example.com/[redacted]'])

        // Offsets advanced only after the write landed.
        expect(offsetStore.offsetsStore).toHaveBeenCalledWith([{ topic: 'ml_block_metadata', partition: 0, offset: 2 }])
    })
})
