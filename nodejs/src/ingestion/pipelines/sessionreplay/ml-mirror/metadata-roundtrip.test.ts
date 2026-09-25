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
import { MlDataKey } from './keys/crypto'
import { decryptEnvelope } from './keys/envelope-testing'
import { MlKeyReader } from './keys/reader'
import { sessionKeyId, tableKeyString } from './keys/schema'
import { MlKafkaTransport } from './keys/transport'
import { MlBlockMetadataSink } from './ml-block-metadata-sink'
import { PSEUDONYM_SESSION, PSEUDONYM_TEAM, pseudonymize } from './pseudonymize'

const SESSION_A = '01a0a4f0-3200-7000-8000-000000000001'
// Starts at 2026-09-22T12:00:00Z, after the v3 cutoff.
const SESSION_V3 = '01a0c8fc-b600-7000-8000-000000000003'

const block = (
    sessionId: string,
    teamId: number,
    distinctId: string,
    startMs = 1789473600000
): SessionBlockMetadata => ({
    ...createNoopBlockMetadata(sessionId, teamId),
    distinctId,
    blockUrl: `s3://ml-bucket/key-${sessionId}?range=bytes=10-42`,
    startDateTime: DateTime.fromMillis(startMs),
    endDateTime: DateTime.fromMillis(startMs + 5000),
    eventCount: 5,
    messageCount: 2,
    clickCount: 1,
    urls: ['https://example.com/[redacted]'],
    snapshotSource: 'web',
    replayIndexEntries: [
        {
            kind: 'page',
            windowId: 'w1',
            eventTimestamp: startMs + 1.5,
            eventIndex: 0,
            url: 'https://example.com/[redacted]',
        },
        { kind: 'full_snapshot', windowId: 'w1', eventTimestamp: startMs + 1.5, eventIndex: 1 },
        {
            kind: 'json_ld',
            windowId: 'w1',
            eventTimestamp: startMs + 1.5,
            eventIndex: 2,
            fullSnapshotTimestamp: startMs + 1.5,
            rootTypes: ['Product'],
        },
        {
            kind: 'page',
            windowId: 'w1',
            eventTimestamp: startMs + 1.5,
            eventIndex: 2,
            url: 'https://example.com/[redacted]',
        },
        { kind: 'json_ld', windowId: 'w1', eventTimestamp: startMs + 1.5, eventIndex: 3, rootTypes: ['Article'] },
    ],
})

const sessionKey = (teamId: number, sessionId: string): MlDataKey => ({
    identity: { teamId, sessionId, organizationId: 'test-org' },
    plaintext: Buffer.alloc(32, 7),
    wrapped: Buffer.from('wrapped'),
})

const keyReader = (keys: MlDataKey[]): MlKeyReader =>
    ({
        read: jest.fn(() =>
            Promise.resolve(
                new Map(
                    keys.map((key) => [tableKeyString(sessionKeyId(key.identity.teamId, key.identity.sessionId!)), key])
                )
            )
        ),
    }) as unknown as MlKeyReader

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
    it('writes v3 as plain Parquet without a session key, encrypts v2, and preserves legacy records', async () => {
        await sodium.ready
        const key = sessionKey(1, SESSION_A)
        // The sink holds no key for the v3 session, so its row lands only if the sink never looks one up.
        const producerReader = keyReader([key, sessionKey(3, SESSION_V3)])
        const sinkReader = keyReader([key])
        // --- Mirror (producer) side: block metadata → Kafka message bytes ---
        const produced: { key?: unknown; value: Buffer | null; headers?: Record<string, string> }[] = []
        const outputs = {
            queueMessages: jest.fn((_output, messages) => {
                produced.push(...messages)
                return Promise.resolve()
            }),
        } as unknown as IngestionOutputs<MlBlockMetadataOutput>

        await new MlBlockMetadataSink(outputs, 'test-secret', producerReader).storeSessionBlocks([
            block(SESSION_A, 1, 'person-1'),
            block('01a0a4f0-31ff-7000-8000-000000000001', 2, 'person-2'),
            block(SESSION_V3, 3, 'person-3', Date.parse('2026-09-22T12:00:00Z')),
        ])
        expect(produced).toHaveLength(3)

        // --- Sink (consumer) side: those exact bytes → parser → batcher → Parquet in S3 ---
        const puts: PutObjectCommandInput[] = []
        const s3 = {
            send: jest.fn((cmd: { input: PutObjectCommandInput }) => {
                puts.push(cmd.input)
                return Promise.resolve({})
            }),
        } as unknown as S3Client
        const store = new BlockMetadataParquetStore(
            s3,
            { v2: 'ml-bucket', v3: 'ml-bucket-v3' },
            'block-metadata',
            'pod-1'
        )
        const offsetStore: OffsetStore = { offsetsStore: jest.fn() }
        const batcher = new BlockMetadataBatcher(
            store,
            offsetStore,
            { flushIntervalMs: 60_000, maxRows: 1_000 },
            0,
            new MlKafkaTransport(sinkReader)
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
        const evalRows = await readRows(
            puts.find((put) => put.Key!.startsWith('block-metadata-replay-index/v2/2026-09/kind=json_ld/'))!.Body
        )
        expect(evalRows).toHaveLength(1)
        expect(evalRows[0]).toMatchObject({ team_id: '1', session_id: SESSION_A })
        expect(evalRows[0].url).toBeUndefined()
        const labelEnvelope = parseJSON(evalRows[0].payload.toString())
        expect(() => decryptEnvelope(key, labelEnvelope, 'replay-index', 'full_snapshot')).toThrow()
        const labels = parseJSON(decryptEnvelope(key, labelEnvelope, 'replay-index', 'json_ld').toString())
        expect(labels).toEqual([
            expect.objectContaining({
                team_id: '1',
                session_id: SESSION_A,
                kind: 'json_ld',
                root_types: ['Product'],
                url: 'https://example.com/[redacted]',
            }),
            expect.objectContaining({
                team_id: '1',
                session_id: SESSION_A,
                kind: 'json_ld',
                root_types: ['Article'],
                url: null,
            }),
        ])
        const v3Metadata = puts.find((put) => put.Key!.startsWith('block-metadata/v3/2026-09/'))!
        expect(v3Metadata.Bucket).toBe('ml-bucket-v3')
        const v3Rows = await readRows(v3Metadata.Body)
        expect(v3Rows).toEqual([
            expect.objectContaining({ team_id: '3', session_id: SESSION_V3, urls: ['https://example.com/[redacted]'] }),
        ])
        expect(v3Rows[0]).not.toHaveProperty('payload')
        expect(v3Rows[0]).not.toHaveProperty('distinct_id')
        const v3Labels = await readRows(
            puts.find((put) => put.Key!.startsWith('block-metadata-replay-index/v3/2026-09/kind=json_ld/'))!.Body
        )
        expect(v3Labels).toEqual([
            expect.objectContaining({
                team_id: '3',
                session_id: SESSION_V3,
                root_types: ['Product'],
                url: 'https://example.com/[redacted]',
            }),
            expect.objectContaining({ team_id: '3', session_id: SESSION_V3, root_types: ['Article'] }),
        ])

        const legacyRows = await readRows(puts.find((put) => put.Key!.startsWith('block-metadata/dt='))!.Body)
        expect(legacyRows).toHaveLength(1)
        expect(legacyRows[0]).not.toHaveProperty('distinct_id')
        expect(legacyRows[0]).toMatchObject({
            team_id: pseudonymize('test-secret', PSEUDONYM_TEAM, '2'),
            session_id: pseudonymize('test-secret', PSEUDONYM_SESSION, '01a0a4f0-31ff-7000-8000-000000000001'),
        })
        const legacyLabels = await readRows(puts.find((put) => put.Key!.includes('v1/kind=json_ld'))!.Body)
        expect(legacyLabels).toHaveLength(2)
        expect(legacyLabels[0].session_id).toBe(legacyRows[0].session_id)

        const bySession = new Map([[decrypted.session_id, decrypted]])
        const a = bySession.get(SESSION_A)!
        expect(a).toBeDefined()
        expect(a.team_id).toBe('1')
        expect(a).not.toHaveProperty('distinct_id')
        expect(a.session_id).toBe(SESSION_A)
        // Real block fields round-trip through JSON → Parquet → read.
        expect(Number(a.block_byte_start)).toBe(10)
        expect(Number(a.block_byte_end)).toBe(42)
        expect(a.event_count).toBe(5)
        expect(a.urls).toEqual(['https://example.com/[redacted]'])

        // Offsets advanced only after the write landed.
        expect(offsetStore.offsetsStore).toHaveBeenCalledWith([{ topic: 'ml_block_metadata', partition: 0, offset: 3 }])
    })
})
