import { BatchGetItemCommand, DynamoDBClient, TransactWriteItemsCommand } from '@aws-sdk/client-dynamodb'
import { GenerateDataKeyCommand, KMSClient } from '@aws-sdk/client-kms'
import { S3Client } from '@aws-sdk/client-s3'
import { Message } from 'node-rdkafka'
import { register } from 'prom-client'

import { parseJSON } from '~/common/utils/json-parse'
import { ok } from '~/ingestion/framework/results'
import { BlockMetadataBatcher } from '~/ingestion/pipelines/sessionreplay/ml-mirror/block-metadata-batcher'
import { BlockMetadataParquetStore } from '~/ingestion/pipelines/sessionreplay/ml-mirror/block-metadata-parquet-store'
import { toBlockMetadataRow } from '~/ingestion/pipelines/sessionreplay/ml-mirror/block-metadata-row'
import { createNoopBlockMetadata } from '~/ingestion/pipelines/sessionreplay/shared/metadata/session-block-metadata'

import { MlPrivacyBatchController } from './batch-controller'
import { MlKeyEncryption } from './crypto'
import { DynamoItem, MlPrivacyDynamoDB, encodeKey } from './dynamodb'
import { MlSessionKeyStore } from './key-store'
import { MlKeyReader } from './reader'
import {
    ML_KEY_SHARDS,
    MlSessionIdentity,
    imageKeyId,
    monthBlockId,
    monthBlockShardId,
    monthKeyIndexId,
    sessionKeyId,
    tableKeyString,
} from './schema'
import { MlKafkaEncryption, encryptedKafkaValue } from './transport'

const session: MlSessionIdentity = {
    teamId: 7,
    organizationId: 'organization-test',
    sessionId: '01994569-4380-7000-8000-000000000007',
}
const table = 'ml-privacy-test'

class DynamoBoundary {
    public readonly items = new Map<string, DynamoItem>()
    public readSizes: number[] = []
    public writeSizes: number[] = []
    public transactionConflicts = 0
    public transactions: string[][] = []
    private readonly pendingWrites = new Set<string>()

    public async send(command: BatchGetItemCommand | TransactWriteItemsCommand): Promise<object> {
        if (command instanceof BatchGetItemCommand) {
            const keys = command.input.RequestItems![table].Keys!
            if (keys.some((key) => Buffer.byteLength(key.sk.S!) > 1024)) {
                throw new Error('DynamoDB sort key exceeds 1024 bytes')
            }
            this.readSizes.push(keys.length)
            return Promise.resolve({
                Responses: {
                    [table]: keys.flatMap((key) => {
                        const value = this.items.get(JSON.stringify([key.pk.S, key.sk.S]))
                        return value ? [value] : []
                    }),
                },
            })
        }
        const actions = command.input.TransactItems!
        this.transactions.push(
            actions.map((action) => {
                const operation = action.ConditionCheck ?? action.Put!
                const key = 'Item' in operation ? operation.Item! : operation.Key!
                return JSON.stringify([key.pk.S, key.sk.S])
            })
        )
        const writes = actions.flatMap((action) =>
            action.Put ? [JSON.stringify([action.Put.Item!.pk.S, action.Put.Item!.sk.S])] : []
        )
        if (writes.some((key) => this.pendingWrites.has(key))) {
            this.transactionConflicts += 1
            throw new Error('Conflicting transaction write')
        }
        writes.forEach((key) => this.pendingWrites.add(key))
        try {
            await Promise.resolve()
            this.writeSizes.push(actions.length)
            for (const action of actions) {
                const operation = action.ConditionCheck ?? action.Put!
                const key = 'Item' in operation ? operation.Item! : operation.Key!
                const current = this.items.get(JSON.stringify([key.pk.S, key.sk.S]))
                const condition = operation.ConditionExpression
                const valid =
                    !condition ||
                    (condition === 'attribute_not_exists(pk)'
                        ? !current
                        : condition === 'attribute_exists(wrapped_key) AND attribute_not_exists(deleted)'
                          ? current?.wrapped_key?.B && !current?.deleted
                          : false)
                if (!valid) {
                    throw new Error('Conditional transaction failed')
                }
            }
            for (const action of actions) {
                if (action.Put) {
                    const item = action.Put.Item!
                    this.items.set(JSON.stringify([item.pk.S, item.sk.S]), item)
                }
            }
            return {}
        } finally {
            writes.forEach((key) => this.pendingWrites.delete(key))
        }
    }
}

function blockMonth(boundary: DynamoBoundary, month: string): void {
    const markers = [
        monthBlockId(month),
        ...Array.from({ length: ML_KEY_SHARDS }, (_, shard) => monthBlockShardId(month, shard)),
    ]
    for (const key of markers) {
        boundary.items.set(tableKeyString(key), { ...encodeKey(key), deleted: { BOOL: true } })
    }
}

describe('ML session key batches', () => {
    let boundary: DynamoBoundary
    let encryption: MlKeyEncryption
    let store: MlSessionKeyStore
    let reader: MlKeyReader
    let generated: number

    beforeEach(async () => {
        boundary = new DynamoBoundary()
        generated = 0
        encryption = new MlKeyEncryption(
            {
                send: jest.fn((command) => {
                    if (command instanceof GenerateDataKeyCommand) {
                        const bytes = Buffer.alloc(32, ++generated)
                        return Promise.resolve({ Plaintext: bytes, CiphertextBlob: bytes })
                    }
                    return Promise.resolve({ Plaintext: command.input.CiphertextBlob })
                }),
            } as unknown as KMSClient,
            'test-key',
            1000,
            60000,
            8,
            1_000_000_000
        )
        await encryption.start()
        const db = new MlPrivacyDynamoDB(boundary as unknown as DynamoDBClient, table)
        store = new MlSessionKeyStore(db, encryption)
        reader = new MlKeyReader(db, encryption)
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it('deduplicates repeated sessions and stores only keys and month indexes', async () => {
        const identities = Array.from({ length: 120 }, () => ({ ...session }))
        const batch = await store.prepare(identities)
        expect(generated).toBe(2)
        await batch.commit()
        expect(boundary.items.size).toBe(4)
        expect(Math.max(...boundary.readSizes)).toBeLessThanOrEqual(100)
        expect(Math.max(...boundary.writeSizes)).toBeLessThanOrEqual(100)
        expect((await reader.read([sessionKeyId(session.teamId, session.sessionId)])).size).toBe(1)
    })

    it('commits concurrent new sessions in bounded transactions', async () => {
        await (await store.prepare([session])).commit()
        const identities = Array.from({ length: 120 }, (_, index) => ({
            ...session,
            sessionId: `01994569-4380-7000-8000-${(index + 100).toString(16).padStart(12, '0')}`,
        }))
        const batches = await Promise.all([store.prepare(identities.slice(0, 60)), store.prepare(identities.slice(60))])
        jest.useFakeTimers()
        const committed = Promise.all(batches.map((batch) => batch.commit()))
        await jest.runAllTimersAsync()
        await committed
        const keys = await reader.read(identities.map((identity) => sessionKeyId(identity.teamId, identity.sessionId)))
        expect(keys.size).toBe(identities.length)
        expect(boundary.transactionConflicts).toBe(0)
    })

    it('indexes monthly keys atomically and blocks a month during a competing batch', async () => {
        const october = { ...session, sessionId: '0199a13b-c000-7000-8000-000000000007' }
        const first = await store.prepare([session, october])
        await first.commit()
        const septemberKeys = first.get(session.teamId, session.sessionId)!
        const octoberKeys = first.get(october.teamId, october.sessionId)!
        expect(septemberKeys.image.plaintext).not.toEqual(octoberKeys.image.plaintext)
        for (const key of [septemberKeys.session, septemberKeys.image, octoberKeys.session, octoberKeys.image]) {
            const location = key.identity.sessionId
                ? sessionKeyId(key.identity.teamId, key.identity.sessionId)
                : imageKeyId(key.identity.teamId, key.identity.sessionMonth!)
            expect(boundary.items.get(tableKeyString(monthKeyIndexId(key.identity, location)))).toMatchObject({
                key_pk: { S: location.pk },
                key_sk: { S: location.sk },
            })
        }
        const inFlight = await store.prepare([session])
        blockMonth(boundary, '2025-09')
        jest.useFakeTimers()
        const committing = inFlight.commit()
        await jest.runAllTimersAsync()
        await committing
        expect(inFlight.get(session.teamId, session.sessionId)).toBeUndefined()
        const locations = [
            sessionKeyId(session.teamId, session.sessionId),
            imageKeyId(session.teamId, '2025-09'),
            sessionKeyId(october.teamId, october.sessionId),
            imageKeyId(session.teamId, '2025-10'),
        ]
        expect([...(await reader.read(locations))].map(([id]) => id)).toEqual(locations.slice(2).map(tableKeyString))
    })

    it('keeps every transaction inside one key shard', async () => {
        const identities = Array.from({ length: 60 }, (_, index) => ({
            ...session,
            sessionId: `01994569-4380-7000-8000-${(index + 300).toString(16).padStart(12, '0')}`,
        }))
        const batch = await store.prepare(identities)
        jest.useFakeTimers()
        const committed = batch.commit()
        await jest.runAllTimersAsync()
        await committed
        const shardsPerTransaction = boundary.transactions.map(
            (keys) => new Set(keys.flatMap((key) => key.match(/:shard:(\d+)","deleted"\]$/)?.[1] ?? []))
        )
        expect(shardsPerTransaction.every((shards) => shards.size === 1)).toBe(true)
        expect(new Set(shardsPerTransaction.flatMap((shards) => [...shards])).size).toBeGreaterThan(1)
    })

    it('honours an unsharded month marker at read time', async () => {
        const blocked = monthBlockId('2025-09')
        boundary.items.set(tableKeyString(blocked), { ...encodeKey(blocked), deleted: { BOOL: true } })
        const batch = await store.prepare([session])
        await batch.commit()
        expect(batch.get(session.teamId, session.sessionId)).toBeUndefined()
        expect(boundary.writeSizes).toEqual([])
    })

    it('adopts a competing writer key', async () => {
        const first = await store.prepare([session])
        const second = await store.prepare([session])
        const provisional = second.get(session.teamId, session.sessionId)!.session.plaintext
        await first.commit()
        jest.useFakeTimers()
        const committing = second.commit()
        await jest.runAllTimersAsync()
        await committing
        expect(second.get(session.teamId, session.sessionId)!.session.plaintext).toEqual(
            first.get(session.teamId, session.sessionId)!.session.plaintext
        )
        expect(second.get(session.teamId, session.sessionId)!.session.plaintext).not.toEqual(provisional)
    })

    it('blocks an existing session deleted during a batch', async () => {
        const first = await store.prepare([session])
        await first.commit()
        const next = await store.prepare([session])
        const blocked = sessionKeyId(session.teamId, session.sessionId)
        boundary.items.set(tableKeyString(blocked), { ...encodeKey(blocked), deleted: { BOOL: true } })
        jest.useFakeTimers()
        const committed = next.commit()
        await jest.runAllTimersAsync()
        await committed
        expect(next.get(session.teamId, session.sessionId)).toBeUndefined()
        expect((await reader.read([sessionKeyId(session.teamId, session.sessionId)])).size).toBe(0)
        expect((await reader.read([imageKeyId(session.teamId, '2025-09')])).size).toBe(1)
    })

    it('reuses the session and monthly image keys across batches', async () => {
        const first = await store.prepare([session])
        await first.commit()
        const original = first.get(session.teamId, session.sessionId)!
        const resumed = await store.prepare([session])
        await resumed.commit()
        const keys = resumed.get(session.teamId, session.sessionId)!
        expect(keys.session.plaintext).toEqual(original.session.plaintext)
        expect(keys.image.plaintext).toEqual(original.image.plaintext)
        expect((await reader.read([sessionKeyId(session.teamId, session.sessionId)])).size).toBe(1)
        expect(generated).toBe(2)
    })

    it('publishes a bounded concurrent batch only after privacy writes commit', async () => {
        const identity = { ...session, sessionId: '01a0a4f0-3200-7000-8000-000000000001' }
        const controller = new MlPrivacyBatchController(store, encryption)
        await controller.prepare([identity])
        let release!: () => void
        const delivery = new Promise<void>((resolve) => {
            release = resolve
        })
        let started = 0
        let firstWaveStarted!: () => void
        const firstWave = new Promise<void>((resolve) => {
            firstWaveStarted = resolve
        })
        const input = {
            team: { teamId: identity.teamId },
            headers: { session_id: identity.sessionId },
            sessionKey: await controller.getKey(identity.sessionId, identity.teamId),
        }
        for (let index = 0; index < 20; index++) {
            await controller.defer(input, (value) => {
                expect(
                    boundary.items.get(tableKeyString(sessionKeyId(identity.teamId, identity.sessionId)))?.wrapped_key
                ).toBeDefined()
                if (++started === 8) {
                    firstWaveStarted()
                }
                return Promise.resolve(ok(value, [delivery]))
            })
        }
        const committed = controller.commit()
        await firstWave
        expect(started).toBe(8)
        release()
        await committed
        expect(started).toBe(20)
    })
    it.each(['invalid-json', 'oversized-session', 'invalid-session', 'invalid-month'])(
        'reports accepted, malformed (%s) and deleted encrypted metadata separately',
        async (malformed) => {
            register.resetMetrics()
            const deleted = { ...session, sessionId: '01994569-4380-7000-8000-000000000008' }
            const batch = await store.prepare([session, deleted])
            await batch.commit()
            const messages = [session, deleted].map((identity, offset) => {
                const encoded = encryptedKafkaValue(
                    batch.get(identity.teamId, identity.sessionId)!.session,
                    'metadata',
                    Buffer.from(
                        JSON.stringify({
                            ...toBlockMetadataRow(
                                {
                                    ...createNoopBlockMetadata(identity.sessionId, identity.teamId),
                                    blockUrl: 's3://bucket/block',
                                },
                                'test'
                            ),
                            session_id: identity.sessionId,
                            team_id: String(identity.teamId),
                            format_version: 2,
                        })
                    )
                )
                return {
                    topic: 'metadata',
                    partition: 0,
                    offset,
                    value: encoded.value,
                    headers: Object.entries(encoded.headers).map(([name, value]) => ({ [name]: Buffer.from(value) })),
                } as Message
            })
            boundary.items.delete(tableKeyString(sessionKeyId(deleted.teamId, deleted.sessionId)))
            const invalidEnvelope = parseJSON(messages[0].value!.toString())
            invalidEnvelope.context.sessionId =
                malformed === 'oversized-session'
                    ? 'a'.repeat(1025)
                    : malformed === 'invalid-month'
                      ? 'ffffffff-ffff-7000-8000-000000000007'
                      : 'not-a-session'
            messages.push({
                ...messages[0],
                offset: 2,
                value: Buffer.from(malformed === 'invalid-json' ? 'invalid' : JSON.stringify(invalidEnvelope)),
            })
            const upload = jest.fn().mockResolvedValue({})
            const offsetsStore = jest.fn()
            const batcher = new BlockMetadataBatcher(
                new BlockMetadataParquetStore(
                    { send: upload } as unknown as S3Client,
                    'ml-bucket',
                    'block-metadata',
                    'pod'
                ),
                { offsetsStore },
                { flushIntervalMs: 1000, maxRows: 1 },
                0,
                new MlKafkaEncryption(reader)
            )
            await batcher.handleBatch(messages, 0)
            expect(upload).toHaveBeenCalledTimes(1)
            expect(offsetsStore).toHaveBeenCalledWith([{ topic: 'metadata', partition: 0, offset: 3 }])
            const accepted = await register.getSingleMetric('ml_mirror_parquet_sink_rows_parsed_total')!.get()
            expect(accepted.values[0].value).toBe(1)
            const rejected = await register.getSingleMetric('ml_mirror_parquet_sink_rows_rejected_total')!.get()
            expect(rejected.values).toEqual(
                expect.arrayContaining([
                    expect.objectContaining({ labels: { reason: 'privacy' }, value: 1 }),
                    expect.objectContaining({ labels: { reason: 'invalid_envelope' }, value: 1 }),
                ])
            )
        }
    )
})
