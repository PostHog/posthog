import {
    BatchGetItemCommand,
    ConditionalCheckFailedException,
    DynamoDBClient,
    PutItemCommand,
} from '@aws-sdk/client-dynamodb'
import { GenerateDataKeyCommand, KMSClient } from '@aws-sdk/client-kms'
import { S3Client } from '@aws-sdk/client-s3'
import { Message } from 'node-rdkafka'
import { register } from 'prom-client'

import { parseJSON } from '~/common/utils/json-parse'
import { PromiseScheduler } from '~/common/utils/promise-scheduler'
import { ok } from '~/ingestion/framework/results'
import { BlockMetadataBatcher } from '~/ingestion/pipelines/sessionreplay/ml-mirror/block-metadata-batcher'
import { BlockMetadataParquetStore } from '~/ingestion/pipelines/sessionreplay/ml-mirror/block-metadata-parquet-store'
import { toBlockMetadataRow } from '~/ingestion/pipelines/sessionreplay/ml-mirror/block-metadata-row'
import { MlMirrorMetrics } from '~/ingestion/pipelines/sessionreplay/ml-mirror/metrics'
import { createNoopBlockMetadata } from '~/ingestion/pipelines/sessionreplay/shared/metadata/session-block-metadata'

import { MlKeyBatchController } from './batch-controller'
import { MlDataKey, MlKeyEncryption } from './crypto'
import { DynamoItem, MlKeyDynamoDB, encodeKey } from './dynamodb'
import { MlSessionKeyStore } from './key-store'
import { MlKeyReader } from './reader'
import {
    MlSessionIdentity,
    TableKey,
    imageKeyId,
    monthKeyIndexId,
    sessionKeyId,
    tableKeyString,
    teamBlockId,
} from './schema'
import { MlKafkaTransport, mlKafkaRecord } from './transport'

const session: MlSessionIdentity = {
    teamId: 7,
    sessionId: '01994569-4380-7000-8000-000000000007',
}
const table = 'ml-keys-test'

function transientError(name: string): Error {
    return Object.assign(new Error(name), { name })
}

class DynamoBoundary {
    public readonly items = new Map<string, DynamoItem>()
    public readSizes: number[] = []
    public writes = 0
    public conditionalFailures = 0

    public async send(command: BatchGetItemCommand | PutItemCommand): Promise<object> {
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
        const item = command.input.Item!
        const id = JSON.stringify([item.pk.S, item.sk.S])
        this.writes += 1
        await Promise.resolve()
        if (command.input.ConditionExpression === 'attribute_not_exists(pk)' && this.items.has(id)) {
            this.conditionalFailures += 1
            throw new ConditionalCheckFailedException({ $metadata: {}, message: 'The conditional request failed' })
        }
        this.items.set(id, item)
        return {}
    }
}

describe('ML session key batches', () => {
    let boundary: DynamoBoundary
    let encryption: MlKeyEncryption
    let store: MlSessionKeyStore
    let reader: MlKeyReader
    let generated: number
    let kmsSend: jest.Mock

    beforeEach(() => {
        boundary = new DynamoBoundary()
        generated = 0
        // Like KMS, a wrapped key only unwraps under the exact encryption context it was wrapped with.
        const wrappedUnder = new Map<string, string>()
        const contextKey = (context?: Record<string, string>): string =>
            JSON.stringify(Object.entries(context ?? {}).sort())
        kmsSend = jest.fn((command) => {
            if (command instanceof GenerateDataKeyCommand) {
                const bytes = Buffer.alloc(32, ++generated)
                wrappedUnder.set(bytes.toString('base64'), contextKey(command.input.EncryptionContext))
                return Promise.resolve({ Plaintext: bytes, CiphertextBlob: bytes })
            }
            const wrapped = Buffer.from(command.input.CiphertextBlob)
            if (wrappedUnder.get(wrapped.toString('base64')) !== contextKey(command.input.EncryptionContext)) {
                return Promise.reject(transientError('InvalidCiphertextException'))
            }
            return Promise.resolve({ Plaintext: wrapped })
        })
        encryption = new MlKeyEncryption(
            { send: kmsSend } as unknown as KMSClient,
            'test-key',
            1000,
            60000,
            8,
            1_000_000_000
        )
        const db = new MlKeyDynamoDB(boundary as unknown as DynamoDBClient, table)
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
        expect(boundary.writes).toBe(4)
        expect((await reader.read([sessionKeyId(session.teamId, session.sessionId)])).size).toBe(1)
    })

    it('commits concurrent new sessions without conditional failures', async () => {
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
        expect(boundary.conditionalFailures).toBe(0)
    })

    it.each([
        ['survives', 7, true],
        ['gives up after', 10, false],
    ])('%s %i consecutive write failures on commit', async (_label, failures, succeeds) => {
        const send = boundary.send.bind(boundary)
        let remaining = failures
        jest.spyOn(boundary, 'send').mockImplementation((command) => {
            if (
                command instanceof PutItemCommand &&
                command.input.Item!.sk.S!.startsWith('session:') &&
                remaining > 0
            ) {
                remaining -= 1
                return Promise.reject(transientError('ProvisionedThroughputExceededException'))
            }
            return send(command)
        })
        const batch = await store.prepare([session])
        jest.useFakeTimers()
        const settled = batch.commit().then(
            () => 'committed',
            () => 'failed'
        )
        await jest.runAllTimersAsync()
        expect(await settled).toBe(succeeds ? 'committed' : 'failed')
        expect(boundary.items.has(tableKeyString(sessionKeyId(session.teamId, session.sessionId)))).toBe(succeeds)
    })

    it('fails fast on a non-retryable write error', async () => {
        const send = boundary.send.bind(boundary)
        jest.spyOn(boundary, 'send').mockImplementation((command) =>
            command instanceof PutItemCommand ? Promise.reject(transientError('ValidationException')) : send(command)
        )
        const batch = await store.prepare([session])
        await expect(batch.commit()).rejects.toThrow('ValidationException')
        expect(boundary.writes).toBeLessThanOrEqual(2)
    })

    it.each([
        ['prepare', 9, true],
        ['prepare', 10, false],
        ['reader', 9, true],
        ['reader', 10, false],
    ])('%s under %i consecutive read throttles succeeds: %s', async (entryPoint, failures, succeeds) => {
        const send = boundary.send.bind(boundary)
        let remaining = failures as number
        jest.spyOn(boundary, 'send').mockImplementation((command) => {
            if (command instanceof BatchGetItemCommand && remaining > 0) {
                remaining -= 1
                return Promise.reject(transientError('RequestLimitExceeded'))
            }
            return send(command)
        })
        jest.useFakeTimers()
        const settled = (
            entryPoint === 'prepare'
                ? store.prepare([session])
                : reader.read([sessionKeyId(session.teamId, session.sessionId)])
        ).then(
            () => 'read',
            () => 'failed'
        )
        await jest.runAllTimersAsync()
        expect(await settled).toBe(succeeds ? 'read' : 'failed')
    })

    it('writes the month index entry before the key and repairs a failed index put', async () => {
        const send = boundary.send.bind(boundary)
        let remaining = 1
        jest.spyOn(boundary, 'send').mockImplementation((command) => {
            if (command instanceof PutItemCommand && command.input.Item!.pk.S!.startsWith('month:') && remaining > 0) {
                remaining -= 1
                return Promise.reject(transientError('ProvisionedThroughputExceededException'))
            }
            return send(command)
        })
        const batch = await store.prepare([session])
        jest.useFakeTimers()
        const committing = batch.commit()
        await jest.runAllTimersAsync()
        await committing
        const location = sessionKeyId(session.teamId, session.sessionId)
        expect(boundary.items.has(tableKeyString(location))).toBe(true)
        expect(boundary.items.has(tableKeyString(monthKeyIndexId({ ...session }, location)))).toBe(true)
    })

    it('keeps its own key when a retried put reports it as already stored', async () => {
        const send = boundary.send.bind(boundary)
        let lostResponses = 1
        jest.spyOn(boundary, 'send').mockImplementation(async (command) => {
            const result = await send(command)
            if (
                command instanceof PutItemCommand &&
                command.input.Item!.sk.S!.startsWith('session:') &&
                lostResponses > 0
            ) {
                lostResponses -= 1
                throw Object.assign(new Error('socket hang up'), { code: 'ECONNRESET' })
            }
            return result
        })
        const batch = await store.prepare([session])
        const candidate = batch.get(session.teamId, session.sessionId)!.session.plaintext
        jest.useFakeTimers()
        const committing = batch.commit()
        await jest.runAllTimersAsync()
        await committing
        expect(batch.get(session.teamId, session.sessionId)!.session.plaintext).toEqual(candidate)
        const location = sessionKeyId(session.teamId, session.sessionId)
        expect(boundary.items.has(tableKeyString(monthKeyIndexId({ ...session }, location)))).toBe(true)
    })

    it('gives up when the commit budget is spent before the attempts are', async () => {
        const send = boundary.send.bind(boundary)
        let remaining = 7
        let slowReads = false
        jest.spyOn(boundary, 'send').mockImplementation(async (command) => {
            if (
                command instanceof PutItemCommand &&
                command.input.Item!.sk.S!.startsWith('session:') &&
                remaining > 0
            ) {
                remaining -= 1
                throw transientError('ProvisionedThroughputExceededException')
            }
            if (command instanceof BatchGetItemCommand && slowReads) {
                await new Promise((resolve) => setTimeout(resolve, 20_000))
            }
            return send(command)
        })
        const batch = await store.prepare([session])
        slowReads = true
        jest.useFakeTimers()
        const settled = batch.commit().then(
            () => 'committed',
            () => 'failed'
        )
        await jest.runAllTimersAsync()
        expect(await settled).toBe('failed')
        expect(remaining).toBeGreaterThan(0)
    })

    it('indexes monthly keys, ignores a month marker, and blocks on a team marker set during a batch', async () => {
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
        const locations = [
            sessionKeyId(session.teamId, session.sessionId),
            imageKeyId(session.teamId, '2025-09'),
            sessionKeyId(october.teamId, october.sessionId),
            imageKeyId(session.teamId, '2025-10'),
        ]
        const monthMarker = { pk: 'month:2025-09', sk: 'deleted' }
        boundary.items.set(tableKeyString(monthMarker), { ...encodeKey(monthMarker), deleted: { BOOL: true } })
        const ignoringMonth = await store.prepare([session])
        jest.useFakeTimers()
        const committingDespiteMonth = ignoringMonth.commit()
        await jest.runAllTimersAsync()
        await committingDespiteMonth
        expect(ignoringMonth.get(session.teamId, session.sessionId)).not.toBeUndefined()
        expect((await reader.read(locations)).size).toBe(4)
        jest.useRealTimers()
        const inFlight = await store.prepare([session])
        const blocked = teamBlockId(session.teamId)
        boundary.items.set(tableKeyString(blocked), { ...encodeKey(blocked), deleted: { BOOL: true } })
        jest.useFakeTimers()
        const committing = inFlight.commit()
        await jest.runAllTimersAsync()
        await committing
        expect(inFlight.get(session.teamId, session.sessionId)).toBeUndefined()
        expect((await reader.read(locations)).size).toBe(0)
    })

    it('wraps new keys without an organization and stores none on the row', async () => {
        const batch = await store.prepare([session])
        await batch.commit()
        const generates = kmsSend.mock.calls
            .map(([command]) => command)
            .filter((c) => c instanceof GenerateDataKeyCommand)
        expect(generates).toHaveLength(2)
        for (const command of generates) {
            expect(command.input.EncryptionContext).not.toHaveProperty('organization_id')
        }
        const stored = boundary.items.get(tableKeyString(sessionKeyId(session.teamId, session.sessionId)))!
        expect(stored).not.toHaveProperty('organization_id')
    })

    it('unwraps a key stored under the organization it was wrapped with', async () => {
        const legacyOrganization = 'organization-legacy'
        const sessionKey = await encryption.generate({
            teamId: session.teamId,
            sessionId: session.sessionId,
            organizationId: legacyOrganization,
        })
        const imageKey = await encryption.generate({
            teamId: session.teamId,
            sessionMonth: '2025-09',
            organizationId: legacyOrganization,
        })
        const rows: Array<[TableKey, MlDataKey]> = [
            [sessionKeyId(session.teamId, session.sessionId), sessionKey],
            [imageKeyId(session.teamId, '2025-09'), imageKey],
        ]
        for (const [location, key] of rows) {
            boundary.items.set(tableKeyString(location), {
                ...encodeKey(location),
                wrapped_key: { B: key.wrapped },
                organization_id: { S: legacyOrganization },
                team_id: { N: String(session.teamId) },
                session_month: { S: '2025-09' },
            })
        }
        encryption.clear()
        const next = await store.prepare([session])
        const keys = next.get(session.teamId, session.sessionId)!
        expect(keys.session.plaintext).toEqual(sessionKey.plaintext)
        expect(keys.image.plaintext).toEqual(imageKey.plaintext)
        expect(keys.session.identity.organizationId).toBe(legacyOrganization)
        await next.commit()
        expect(boundary.writes).toBe(0)
    })

    it('cannot unwrap a stored key under a context it was not wrapped with', async () => {
        const sessionKey = await encryption.generate({
            teamId: session.teamId,
            sessionId: session.sessionId,
            organizationId: 'organization-legacy',
        })
        const location = sessionKeyId(session.teamId, session.sessionId)
        boundary.items.set(tableKeyString(location), {
            ...encodeKey(location),
            wrapped_key: { B: sessionKey.wrapped },
            team_id: { N: String(session.teamId) },
            session_month: { S: '2025-09' },
        })
        encryption.clear()
        await expect(store.prepare([session])).rejects.toThrow('InvalidCiphertextException')
    })

    it.each([
        ['session', () => sessionKeyId(session.teamId, session.sessionId)],
        ['monthly image', () => imageKeyId(session.teamId, '2025-09')],
    ])(
        'drops the sessions behind a stored %s key that has no wrapped key and no tombstone, reporting it once',
        async (_kind, keyId) => {
            const first = await store.prepare([session])
            await first.commit()
            const location = tableKeyString(keyId())
            const { wrapped_key: _wrapped, ...stored } = boundary.items.get(location)!
            boundary.items.set(location, stored)
            const unusable = jest.spyOn(MlMirrorMetrics, 'incrementMlKeyIdentityMismatch')
            const next = await store.prepare([session])
            expect(next.get(session.teamId, session.sessionId)).toBeUndefined()
            await next.commit()
            expect(boundary.items.get(location)).toEqual(stored)
            expect(unusable).toHaveBeenCalledTimes(1)
            expect(unusable).toHaveBeenCalledWith('wrapped_key_missing', 1)
        }
    )

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

    it('publishes only after key writes commit and hands delivery acks to the scheduler', async () => {
        const identity = { ...session, sessionId: '01a0a4f0-3200-7000-8000-000000000001' }
        const controller = new MlKeyBatchController(store, encryption)
        await controller.prepare([identity])
        let release!: () => void
        const delivery = new Promise<void>((resolve) => {
            release = resolve
        })
        let started = 0
        const input = {
            team: { teamId: identity.teamId },
            headers: { session_id: identity.sessionId },
            sessionKey: await controller.getKey(identity.sessionId, identity.teamId),
        }
        for (let index = 0; index < 20; index++) {
            await controller.defer(input, (value) => {
                expect(
                    boundary.items.get(tableKeyString(sessionKeyId(identity.teamId, identity.sessionId)))?.wrapped_key
                ).not.toBeUndefined()
                started += 1
                return Promise.resolve(ok(value, [delivery]))
            })
        }
        const scheduler = new PromiseScheduler()
        await controller.commit(scheduler)
        expect(started).toBe(20)
        expect(scheduler.promises.size).toBe(1)
        release()
        await scheduler.waitForAll()
        expect(scheduler.promises.size).toBe(0)
    })

    it('waits for delivery acks itself when no scheduler owns them', async () => {
        const identity = { ...session, sessionId: '01a0a4f0-3200-7000-8000-000000000002' }
        const controller = new MlKeyBatchController(store, encryption)
        await controller.prepare([identity])
        let release!: () => void
        const delivery = new Promise<void>((resolve) => {
            release = resolve
        })
        const input = {
            team: { teamId: identity.teamId },
            headers: { session_id: identity.sessionId },
            sessionKey: await controller.getKey(identity.sessionId, identity.teamId),
        }
        await controller.defer(input, (value) => Promise.resolve(ok(value, [delivery])))
        let committed = false
        const committing = controller.commit().then(() => {
            committed = true
        })
        await new Promise((resolve) => setImmediate(resolve))
        expect(committed).toBe(false)
        release()
        await committing
        expect(committed).toBe(true)
    })
    it.each(['invalid-json', 'oversized-session', 'invalid-session', 'invalid-month'])(
        'reports accepted, malformed (%s) and deleted metadata rows separately',
        async (malformed) => {
            register.resetMetrics()
            const deleted = { ...session, sessionId: '01994569-4380-7000-8000-000000000008' }
            const batch = await store.prepare([session, deleted])
            await batch.commit()
            const messages = [session, deleted].map((identity, offset) => {
                const encoded = mlKafkaRecord(
                    '2',
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
            const invalidRow = parseJSON(messages[0].value!.toString())
            invalidRow.session_id =
                malformed === 'oversized-session'
                    ? 'a'.repeat(1025)
                    : malformed === 'invalid-month'
                      ? 'ffffffff-ffff-7000-8000-000000000007'
                      : 'not-a-session'
            messages.push({
                ...messages[0],
                offset: 2,
                value: Buffer.from(malformed === 'invalid-json' ? 'invalid' : JSON.stringify(invalidRow)),
            })
            messages.push({
                ...messages[0],
                offset: 3,
                value: Buffer.from(
                    JSON.stringify({ v: 2, context: { teamId: 7 }, nonce: 'AwMD', ciphertext: 'J7ZDxBv0xIHU' })
                ),
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
                new MlKafkaTransport(reader)
            )
            await batcher.handleBatch(messages, 0)
            expect(upload).toHaveBeenCalledTimes(1)
            expect(offsetsStore).toHaveBeenCalledWith([{ topic: 'metadata', partition: 0, offset: 4 }])
            const legacy = await register
                .getSingleMetric('recording_blob_ingestion_v2_ml_legacy_envelopes_dropped_total')!
                .get()
            expect(legacy.values[0].value).toBe(1)
            const accepted = await register.getSingleMetric('ml_mirror_parquet_sink_rows_parsed_total')!.get()
            expect(accepted.values[0].value).toBe(1)
            const rejected = await register.getSingleMetric('ml_mirror_parquet_sink_rows_rejected_total')!.get()
            expect(rejected.values).toEqual(
                expect.arrayContaining([
                    expect.objectContaining({ labels: { reason: 'key_missing' }, value: 1 }),
                    expect.objectContaining({ labels: { reason: 'invalid_record' }, value: 1 }),
                ])
            )
        }
    )
})
