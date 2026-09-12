import { PutObjectCommandInput, S3Client } from '@aws-sdk/client-s3'
import { ParquetReader } from '@dsnp/parquetjs'
import sodium from 'libsodium-wrappers'
import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'

import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { parseJSON } from '~/common/utils/json-parse'
import {
    SessionBlockMetadata,
    createNoopBlockMetadata,
} from '~/ingestion/pipelines/sessionreplay/shared/metadata/session-block-metadata'
import { MlBlockMetadataOutput } from '~/ingestion/pipelines/sessionreplay/shared/outputs'

import { BlockMetadataBatcher, OffsetStore } from './block-metadata-batcher'
import { BlockMetadataParquetStore } from './block-metadata-parquet-store'
import { MlBlockMetadataSink } from './ml-block-metadata-sink'
import { MlDataKey, decryptEnvelope } from './privacy/crypto'
import { MlKeyReader } from './privacy/reader'
import { sessionKeyId, tableKeyString } from './privacy/schema'
import { MlKafkaEncryption } from './privacy/transport'
import { PSEUDONYM_DISTINCT_ID, PSEUDONYM_SESSION, PSEUDONYM_TEAM, pseudonymize } from './pseudonymize'

const SESSION_A = '01a09f92-e780-7000-8000-000000000001'

const block = (sessionId: string, teamId: number, distinctId: string): SessionBlockMetadata => ({
    ...createNoopBlockMetadata(sessionId, teamId),
    distinctId,
    blockUrl: `s3://ml-bucket/key-${sessionId}?range=bytes=10-42`,
    startDateTime: DateTime.fromMillis(1789383600000),
    endDateTime: DateTime.fromMillis(1789383605000),
    eventCount: 5,
    messageCount: 2,
    clickCount: 1,
    urls: ['https://example.com/[redacted]'],
    snapshotSource: 'web',
    replayIndexEntries: [
        {
            kind: 'page',
            windowId: 'w1',
            eventTimestamp: 1789383600001.5,
            eventIndex: 0,
            url: 'https://example.com/[redacted]',
        },
        { kind: 'full_snapshot', windowId: 'w1', eventTimestamp: 1789383600001.5, eventIndex: 1 },
        {
            kind: 'json_ld',
            windowId: 'w1',
            eventTimestamp: 1789383600001.5,
            eventIndex: 2,
            fullSnapshotTimestamp: 1789383600001.5,
            rootTypes: ['Product'],
        },
        {
            kind: 'page',
            windowId: 'w1',
            eventTimestamp: 1789383600001.5,
            eventIndex: 2,
            url: 'https://example.com/[redacted]',
        },
        { kind: 'json_ld', windowId: 'w1', eventTimestamp: 1789383600001.5, eventIndex: 3, rootTypes: ['Article'] },
    ],
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
    it('encrypts v2 metadata and replay indexes while preserving legacy records', async () => {
        await sodium.ready
        const key: MlDataKey = {
            identity: { teamId: 1, sessionId: SESSION_A, organizationId: 'test-org', consentGrantedAt: 1789380000000 },
            plaintext: Buffer.alloc(32, 7),
            wrapped: Buffer.from('wrapped'),
        }
        const reader = {
            read: jest.fn(() => Promise.resolve(new Map([[tableKeyString(sessionKeyId(1, SESSION_A)), key]]))),
        } as unknown as MlKeyReader
        // --- Mirror (producer) side: block metadata → Kafka message bytes ---
        const produced: { key?: unknown; value: Buffer | null; headers?: Record<string, string> }[] = []
        const outputs = {
            queueMessages: jest.fn((_output, messages) => {
                produced.push(...messages)
                return Promise.resolve()
            }),
        } as unknown as IngestionOutputs<MlBlockMetadataOutput>

        await new MlBlockMetadataSink(outputs, 'test-secret', reader).storeSessionBlocks([
            block(SESSION_A, 1, 'person-1'),
            block('01a09f92-e77f-7000-8000-000000000001', 2, 'person-2'),
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
        const batcher = new BlockMetadataBatcher(
            store,
            offsetStore,
            { flushIntervalMs: 60_000, maxRows: 1_000 },
            0,
            new MlKafkaEncryption(reader)
        )

        const messages = produced.map(
            (m, i) =>
                ({
                    topic: 'ml_block_metadata',
                    partition: 0,
                    offset: i,
                    value: m.value,
                    headers: Object.entries(m.headers ?? {}).map(([name, value]) => ({ [name]: Buffer.from(value) })),
                }) as Message
        )
        await batcher.handleBatch(messages, 0)
        await batcher.flush(1) // force the window out

        const rows = await readRows(puts.find((put) => put.Key!.startsWith('block-metadata/v2/2026-09/'))!.Body)
        expect(rows).toHaveLength(1)
        expect(rows[0].distinct_id).toBeUndefined()
        expect(rows[0].urls).toBeUndefined()
        const decrypted = parseJSON(decryptEnvelope(key, parseJSON(rows[0].payload.toString()), 'metadata').toString())
        expect(decrypted.replay_index_entries).toHaveLength(5)
        expect(puts.some((put) => put.Key!.includes('replay-index/v2'))).toBe(false)
        const legacyRows = await readRows(puts.find((put) => put.Key!.startsWith('block-metadata/dt='))!.Body)
        expect(legacyRows).toHaveLength(1)
        expect(legacyRows[0]).toMatchObject({
            team_id: pseudonymize('test-secret', PSEUDONYM_TEAM, '2'),
            session_id: pseudonymize('test-secret', PSEUDONYM_SESSION, '01a09f92-e77f-7000-8000-000000000001'),
            distinct_id: pseudonymize('test-secret', PSEUDONYM_DISTINCT_ID, 'person-2'),
        })
        const legacyLabels = await readRows(puts.find((put) => put.Key!.includes('v1/kind=json_ld'))!.Body)
        expect(legacyLabels).toHaveLength(2)
        expect(legacyLabels[0].session_id).toBe(legacyRows[0].session_id)

        const bySession = new Map([[decrypted.session_id, decrypted]])
        const a = bySession.get(SESSION_A)!
        expect(a).toBeDefined()
        expect(a.team_id).toBe('1')
        expect(a.distinct_id).toBe('person-1')
        expect(a.session_id).toBe(SESSION_A)
        // Real block fields round-trip through JSON → Parquet → read.
        expect(Number(a.block_byte_start)).toBe(10)
        expect(Number(a.block_byte_end)).toBe(42)
        expect(a.event_count).toBe(5)
        expect(a.urls).toEqual(['https://example.com/[redacted]'])

        // Offsets advanced only after the write landed.
        expect(offsetStore.offsetsStore).toHaveBeenCalledWith([{ topic: 'ml_block_metadata', partition: 0, offset: 2 }])
    })
})
