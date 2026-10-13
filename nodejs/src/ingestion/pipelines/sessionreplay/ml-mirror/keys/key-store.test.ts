import {
    BatchGetItemCommand,
    BatchWriteItemCommand,
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
import { MlBatchHandle } from '~/ingestion/pipelines/sessionreplay/ml-mirror/batch-handle'
import { BlockMetadataBatcher } from '~/ingestion/pipelines/sessionreplay/ml-mirror/block-metadata-batcher'
import { BlockMetadataParquetStore } from '~/ingestion/pipelines/sessionreplay/ml-mirror/block-metadata-parquet-store'
import { toBlockMetadataRow } from '~/ingestion/pipelines/sessionreplay/ml-mirror/block-metadata-row'
import { MlMirrorMetrics } from '~/ingestion/pipelines/sessionreplay/ml-mirror/metrics'
import { SessionBatchRecorder } from '~/ingestion/pipelines/sessionreplay/sessions/session-batch-recorder'
import { createNoopBlockMetadata } from '~/ingestion/pipelines/sessionreplay/shared/metadata/session-block-metadata'

import { MlKeyBatchController } from './batch-controller'
import { MlDataKey, MlKeyEncryption } from './crypto'
import { DynamoItem, MlKeyDynamoDB, encodeKey } from './dynamodb'
import { MlSessionKeyStore } from './key-store'
import { MlKeyReader } from './reader'
import { MlSessionIdentity, TableKey, imageKeyId, monthKeyIndexId, sessionKeyId, tableKeyString } from './schema'
import { MlKafkaTransport, mlKafkaRecord } from './transport'

const session: MlSessionIdentity = {
    teamId: 7,
    sessionId: '01994569-4380-7000-8000-000000000007',
}
const table = 'ml-keys-test'

const recorder = {
    record: jest.fn(),
    getRetention: jest.fn(),
    flush: jest.fn(),
    size: 0,
} as unknown as SessionBatchRecorder

function transientError(name: string): Error {
    return Object.assign(new Error(name), { name })
}

class DynamoBoundary {
    public readonly items = new Map<string, DynamoItem>()
    public readSizes: number[] = []
    public readKeys: string[][] = []
    public writes = 0
    public writeRequests = 0
    public deferWrites = 0
    public writeBatchSizes: number[] = []
    public conditionalFailures = 0

    public async send(command: BatchGetItemCommand | BatchWriteItemCommand | PutItemCommand): Promise<object> {
        if (command instanceof BatchWriteItemCommand) {
            const requests = command.input.RequestItems![table]
            if (requests.length > 25) {
                throw new Error(`BatchWriteItem takes at most 25 rows, got ${requests.length}`)
            }
            this.writeBatchSizes.push(requests.length)
            this.writeRequests += 1
            await Promise.resolve()
            // DynamoDB answers a partial throttle by storing some rows and returning the rest as unprocessed.
            const deferred = Math.min(this.deferWrites, requests.length)
            this.deferWrites -= deferred
            for (const request of requests.slice(deferred)) {
                const row = request.PutRequest!.Item!
                this.writes += 1
                this.items.set(JSON.stringify([row.pk.S, row.sk.S]), row)
            }
            return deferred ? { UnprocessedItems: { [table]: requests.slice(0, deferred) } } : {}
        }
        if (command instanceof BatchGetItemCommand) {
            const keys = command.input.RequestItems![table].Keys!
            if (keys.some((key) => Buffer.byteLength(key.sk.S!) > 1024)) {
                throw new Error('DynamoDB sort key exceeds 1024 bytes')
            }
            this.readSizes.push(keys.length)
            this.readKeys.push(keys.map((key) => JSON.stringify([key.pk.S, key.sk.S])))
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
        this.writeRequests += 1
        await Promise.resolve()
        if (command.input.ConditionExpression === 'attribute_not_exists(pk)' && this.items.has(id)) {
            this.conditionalFailures += 1
            throw Object.assign(
                new ConditionalCheckFailedException({ $metadata: {}, message: 'The conditional request failed' }),
                command.input.ReturnValuesOnConditionCheckFailure === 'ALL_OLD' ? { Item: this.items.get(id) } : {}
            )
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
        coldCache()
    })

    function coldCache(): void {
        const db = new MlKeyDynamoDB(boundary as unknown as DynamoDBClient, table)
        store = new MlSessionKeyStore(db, encryption)
        reader = new MlKeyReader(db, encryption)
    }

    afterEach(() => {
        jest.useRealTimers()
    })

    it('deduplicates repeated sessions and stores only keys and month indexes', async () => {
        const identities = Array.from({ length: 120 }, () => ({ ...session }))
        const batch = await store.prepare(identities)
        // KMS makes the team month key. The lane makes each session key locally and seals it under that key.
        expect(generated).toBe(1)
        await batch.commit()
        expect(boundary.items.size).toBe(4)
        expect(Math.max(...boundary.readSizes)).toBeLessThanOrEqual(100)
        expect(boundary.writes).toBe(4)
        expect((await reader.read([sessionKeyId(session.teamId, session.sessionId)])).size).toBe(1)
    })

    it.each([
        ['retries only the rows a batch write left unprocessed', 1, true],
        ['gives up when a batch write keeps leaving rows unprocessed', 500, false],
    ])('%s', async (_label, deferred, succeeds) => {
        boundary.deferWrites = deferred
        const batch = await store.prepare([session])
        jest.useFakeTimers()
        const settled = batch.commit().then(
            () => 'committed',
            () => 'failed'
        )
        await jest.runAllTimersAsync()
        expect(await settled).toBe(succeeds ? 'committed' : 'failed')
        if (succeeds) {
            const location = sessionKeyId(session.teamId, session.sessionId)
            expect(boundary.items.has(tableKeyString(monthKeyIndexId({ ...session }, location)))).toBe(true)
            // Two index rows and two keys. A retry that re-sent the whole batch would store an index row twice.
            expect(boundary.writes).toBe(4)
            // Each phase makes one batch write, the retry carries the deferred row, and each key takes one put.
            expect(boundary.writeRequests).toBe(5)
        }
    })

    it('writes one request per key instead of two by batching the month index entries', async () => {
        const identities = Array.from({ length: 60 }, (_, index) => ({
            ...session,
            sessionId: `01994569-4380-7000-8000-${(index + 200).toString(16).padStart(12, '0')}`,
        }))
        const batch = await store.prepare(identities)
        jest.useFakeTimers()
        const committing = batch.commit()
        await jest.runAllTimersAsync()
        await committing
        // 60 session keys and one team image key. Each is one conditional put, and their 61 index entries pack into
        // three batches of at most 25, so 122 requests become 64.
        expect(boundary.writes).toBe(122)
        // The team month key commits before the keys it seals, so that phase adds one request.
        expect(boundary.writeRequests).toBe(65)
        expect([...boundary.writeBatchSizes].sort((a, b) => b - a)).toEqual([25, 25, 10, 1])
    })

    it('reads every row a batch needs in one pass', async () => {
        const readsBefore = boundary.readSizes.length
        await store.prepare([session])
        // The session key and the team image key are known up front, so they go in one request.
        expect(boundary.readSizes.length - readsBefore).toBe(1)
        expect(new Set(boundary.readKeys.at(-1))).toEqual(
            new Set(
                [sessionKeyId(session.teamId, session.sessionId), imageKeyId(session.teamId, '2025-09')].map(
                    tableKeyString
                )
            )
        )
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
        // These 120 sessions share one team month, so KMS made one key.
        expect(generated).toBe(1)
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
        ['prepare', 5, true],
        ['prepare', 6, false],
        ['reader', 5, true],
        ['reader', 6, false],
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

    it('sends no further request when the deadline aborts during a retry delay', async () => {
        const db = new MlKeyDynamoDB(boundary as unknown as DynamoDBClient, table)
        const budget = new AbortController()
        let sends = 0
        jest.spyOn(boundary, 'send').mockImplementation(() => {
            sends += 1
            return Promise.reject(transientError('ThrottlingException'))
        })
        jest.useFakeTimers()
        const settled = db.read([sessionKeyId(session.teamId, session.sessionId)], budget.signal).then(
            () => 'read',
            () => 'failed'
        )
        await jest.advanceTimersByTimeAsync(0)
        budget.abort()
        await jest.runAllTimersAsync()
        expect(await settled).toBe('failed')
        expect(sends).toBe(1)
    })

    it('stops a read when the caller deadline aborts instead of waiting out its attempts', async () => {
        const db = new MlKeyDynamoDB(boundary as unknown as DynamoDBClient, table)
        let attempts = 0
        jest.spyOn(boundary, 'send').mockImplementation(() => {
            attempts += 1
            return Promise.reject(transientError('AbortError'))
        })
        jest.useFakeTimers()
        const settled = db.read([sessionKeyId(session.teamId, session.sessionId)], AbortSignal.abort()).then(
            () => 'read',
            () => 'failed'
        )
        await jest.runAllTimersAsync()
        expect(await settled).toBe('failed')
        expect(attempts).toBe(1)
    })

    it('writes the month index entry before the key and repairs a failed index put', async () => {
        const send = boundary.send.bind(boundary)
        let remaining = 1
        jest.spyOn(boundary, 'send').mockImplementation((command) => {
            if (command instanceof BatchWriteItemCommand && remaining > 0) {
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

    it('indexes monthly keys and ignores a month marker', async () => {
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
    })

    it('wraps new keys without an organization and stores none on the row', async () => {
        const batch = await store.prepare([session])
        await batch.commit()
        const generates = kmsSend.mock.calls
            .map(([command]) => command)
            .filter((c) => c instanceof GenerateDataKeyCommand)
        expect(generates).toHaveLength(1)
        for (const command of generates) {
            expect(command.input.EncryptionContext).not.toHaveProperty('organization_id')
        }
        const stored = boundary.items.get(tableKeyString(sessionKeyId(session.teamId, session.sessionId)))!
        expect(stored).not.toHaveProperty('organization_id')
        expect(stored).toHaveProperty('sealed_key')
        expect(stored).not.toHaveProperty('wrapped_key')
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
        // A session key opens under its month key only, so an unusable month key makes its sessions unusable too.
        ['session', () => sessionKeyId(session.teamId, session.sessionId), [['wrapped_key_missing', 1]]],
        [
            'monthly image',
            () => imageKeyId(session.teamId, '2025-09'),
            [
                ['month_key_unavailable', 1],
                ['wrapped_key_missing', 1],
            ],
        ],
    ])(
        'drops the sessions behind a stored %s key that has no wrapped key and no tombstone, naming why',
        async (_kind, keyId, reported) => {
            const first = await store.prepare([session])
            await first.commit()
            const location = tableKeyString(keyId())
            const { wrapped_key: _wrapped, sealed_key: _sealed, ...stored } = boundary.items.get(location)!
            boundary.items.set(location, stored)
            coldCache()
            const unusable = jest.spyOn(MlMirrorMetrics, 'incrementMlKeyIdentityMismatch')
            const next = await store.prepare([session])
            expect(next.get(session.teamId, session.sessionId)).toBeUndefined()
            await next.commit()
            expect(boundary.items.get(location)).toEqual(stored)
            expect(unusable.mock.calls.sort()).toEqual(reported)
        }
    )

    it('leaves the team month key out of the scheme counter, so v2 can reach zero', async () => {
        const scheme = jest.spyOn(MlMirrorMetrics, 'incrementMlKeyScheme')
        await (await store.prepare([session])).commit()
        coldCache()
        await store.prepare([session])
        expect(scheme.mock.calls.map(([value]) => value)).toEqual(['v3'])
    })

    it('counts a session key that KMS wrapped as v2', async () => {
        const sessionKey = await encryption.generate({ teamId: session.teamId, sessionId: session.sessionId })
        const location = sessionKeyId(session.teamId, session.sessionId)
        boundary.items.set(tableKeyString(location), {
            ...encodeKey(location),
            wrapped_key: { B: sessionKey.wrapped },
            team_id: { N: String(session.teamId) },
            session_month: { S: '2025-09' },
        })
        const scheme = jest.spyOn(MlMirrorMetrics, 'incrementMlKeyScheme')
        await store.prepare([session])
        expect(scheme.mock.calls.map(([value]) => value)).toEqual(['v2'])
    })

    it('drops the sessions of a month key that lost its put to a tombstone, and still commits', async () => {
        const batch = await store.prepare([session])
        const monthLocation = imageKeyId(session.teamId, '2025-09')
        boundary.items.set(tableKeyString(monthLocation), { ...encodeKey(monthLocation), deleted: { BOOL: true } })
        await expect(batch.commit()).resolves.toBeUndefined()
        expect(batch.get(session.teamId, session.sessionId)).toBeUndefined()
        expect(boundary.items.has(tableKeyString(sessionKeyId(session.teamId, session.sessionId)))).toBe(false)
    })

    it('leaves the team month key out of the reader scheme counter, so v2 can reach zero', async () => {
        await (await store.prepare([session])).commit()
        coldCache()
        const scheme = jest.spyOn(MlMirrorMetrics, 'incrementMlKeyScheme')
        await reader.read([imageKeyId(session.teamId, '2025-09')])
        expect(scheme).not.toHaveBeenCalled()
        await reader.read([sessionKeyId(session.teamId, session.sessionId)])
        expect(scheme.mock.calls.map(([value]) => value)).toEqual(['v3'])
    })

    it('drops the sessions of a month key that KMS refuses, and still serves the rest of the batch', async () => {
        const other = { ...session, sessionId: '01994569-4380-7000-8000-00000000000a' }
        await (await store.prepare([session, other])).commit()
        coldCache()
        const monthLocation = tableKeyString(imageKeyId(session.teamId, '2025-09'))
        const stored = boundary.items.get(monthLocation)!
        boundary.items.set(monthLocation, { ...stored, wrapped_key: { B: Buffer.from('not-a-kms-blob') } })
        const legacy = sessionKeyId(other.teamId, '01994569-4380-7000-8000-00000000000b')
        const legacyKey = await encryption.generate({
            teamId: other.teamId,
            sessionId: legacy.sk.slice('session:'.length),
        })
        boundary.items.set(tableKeyString(legacy), {
            ...encodeKey(legacy),
            wrapped_key: { B: legacyKey.wrapped },
            team_id: { N: String(other.teamId) },
            session_month: { S: '2025-09' },
        })
        const mismatch = jest.spyOn(MlMirrorMetrics, 'incrementMlKeyIdentityMismatch')
        const keys = await reader.read([
            sessionKeyId(session.teamId, session.sessionId),
            sessionKeyId(other.teamId, other.sessionId),
            legacy,
        ])
        expect(keys.has(tableKeyString(sessionKeyId(session.teamId, session.sessionId)))).toBe(false)
        expect(keys.has(tableKeyString(sessionKeyId(other.teamId, other.sessionId)))).toBe(false)
        expect(keys.has(tableKeyString(legacy))).toBe(true)
        // One refused month key counts once, however many sessions needed it, so the writer and the reader mean the same thing.
        expect(mismatch.mock.calls).toEqual([['month_key_unavailable', 1]])
    })

    it('fails the read when KMS throttles a month key, so the caller retries instead of dropping', async () => {
        await (await store.prepare([session])).commit()
        coldCache()
        encryption.clear()
        kmsSend.mockImplementation(() => Promise.reject(transientError('ThrottlingException')))
        await expect(reader.read([sessionKeyId(session.teamId, session.sessionId)])).rejects.toThrow(
            'ThrottlingException'
        )
    })

    it('counts an unusable row once however often the batch re-reads it', async () => {
        await (await store.prepare([session])).commit()
        const location = tableKeyString(sessionKeyId(session.teamId, session.sessionId))
        const { sealed_key: _sealed, ...stripped } = boundary.items.get(location)!
        boundary.items.set(location, stripped)
        coldCache()
        const mismatch = jest.spyOn(MlMirrorMetrics, 'incrementMlKeyIdentityMismatch')
        const batch = await store.prepare([session])
        await batch.read()
        await batch.read()
        expect(mismatch.mock.calls).toEqual([['wrapped_key_missing', 1]])
    })

    it('drops a session whose seal does not open, and still serves the rest of the batch', async () => {
        const other = { ...session, sessionId: '01994569-4380-7000-8000-000000000009' }
        await (await store.prepare([session, other])).commit()
        const location = sessionKeyId(session.teamId, session.sessionId)
        const stored = boundary.items.get(tableKeyString(location))!
        boundary.items.set(tableKeyString(location), { ...stored, sealed_key: { B: Buffer.alloc(48, 9) } })
        coldCache()
        const mismatch = jest.spyOn(MlMirrorMetrics, 'incrementMlKeyIdentityMismatch')
        const next = await store.prepare([session, other])
        expect(next.get(session.teamId, session.sessionId)).toBeUndefined()
        expect(next.get(other.teamId, other.sessionId)).not.toBeUndefined()
        expect(mismatch).toHaveBeenCalledWith('seal_unopenable', 1)
    })

    it('adopts a competing writer key when the refusal omits the stored row', async () => {
        const send = boundary.send.bind(boundary)
        jest.spyOn(boundary, 'send').mockImplementation((command) => {
            if (command instanceof PutItemCommand) {
                // An endpoint that does not implement ReturnValuesOnConditionCheckFailure refuses without the row.
                delete (command.input as { ReturnValuesOnConditionCheckFailure?: string })
                    .ReturnValuesOnConditionCheckFailure
            }
            return send(command)
        })
        const first = await store.prepare([session])
        const second = await store.prepare([session])
        await first.commit()
        jest.useFakeTimers()
        const committing = second.commit()
        await jest.runAllTimersAsync()
        await committing
        expect(second.get(session.teamId, session.sessionId)!.session.plaintext).toEqual(
            first.get(session.teamId, session.sessionId)!.session.plaintext
        )
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

    it.each([
        ['a fractional value', 30_000.5],
        ['an unparsable value', Number.NaN],
        ['a zero', 0],
    ])('refuses to start on %s cache setting', (_label, configured) => {
        expect(
            () =>
                new MlKeyDynamoDB(boundary as unknown as DynamoDBClient, table, undefined, undefined, 1000, configured)
        ).toThrow('AI_RESEARCH_REPLAY_ROW_CACHE_LIFETIME_MS')
    })

    it.each([
        ['a lifetime over the cap is clamped', 86_400_000, 300_001, false],
        ['a lifetime under the cap is kept', 60_000, 60_001, false],
        ['a team image key is held past the session lifetime', 86_400_000, 300_001, true],
    ])('%s', async (_label, configured, elapsedMs, imageKey) => {
        let fakeNow = 1_000
        const clock = jest.spyOn(performance, 'now').mockImplementation(() => fakeNow)
        try {
            const db = new MlKeyDynamoDB(
                boundary as unknown as DynamoDBClient,
                table,
                undefined,
                undefined,
                1000,
                configured
            )
            const location = imageKey
                ? imageKeyId(session.teamId, '2025-09')
                : sessionKeyId(session.teamId, session.sessionId)
            await (await new MlSessionKeyStore(db, encryption).prepare([session])).commit()
            const reader = new MlKeyReader(db, encryption)
            expect((await reader.read([location])).size).toBe(1)
            boundary.items.set(tableKeyString(location), { ...encodeKey(location), deleted: { BOOL: true } })
            fakeNow += elapsedMs
            expect((await reader.read([location])).size).toBe(imageKey ? 1 : 0)
        } finally {
            clock.mockRestore()
        }
    })

    it('stops a team month for good once its month key is shredded, so no block row is needed', async () => {
        await (await store.prepare([session])).commit()
        const monthLocation = tableKeyString(imageKeyId(session.teamId, '2025-09'))
        const { wrapped_key: _shredded, ...tombstone } = boundary.items.get(monthLocation)!
        const shreddedRow = { ...tombstone, deleted: { BOOL: true } }
        boundary.items.set(monthLocation, shreddedRow)
        coldCache()
        const writesBefore = boundary.writes
        const next = await store.prepare([session])
        await next.commit()
        expect(next.get(session.teamId, session.sessionId)).toBeUndefined()
        expect(boundary.items.get(monthLocation)).toEqual(shreddedRow)
        expect(boundary.writes).toBe(writesBefore)
    })

    it('holds a session tombstone so a deleted session stops costing a read and a doomed write', async () => {
        const db = new MlKeyDynamoDB(boundary as unknown as DynamoDBClient, table)
        const store = new MlSessionKeyStore(db, encryption)
        const location = sessionKeyId(session.teamId, session.sessionId)
        await (await store.prepare([session])).commit()
        boundary.items.set(tableKeyString(location), { ...encodeKey(location), deleted: { BOOL: true } })
        const cold = new MlSessionKeyStore(new MlKeyDynamoDB(boundary as unknown as DynamoDBClient, table), encryption)
        const first = await cold.prepare([session])
        expect(first.get(session.teamId, session.sessionId)).toBeUndefined()
        const readsBefore = boundary.readSizes.length
        const writesBefore = boundary.writes
        const next = await cold.prepare([session])
        await next.commit()
        expect(next.get(session.teamId, session.sessionId)).toBeUndefined()
        // The tombstone spares the session key row and the image key row, and no row is read at all.
        expect(boundary.readSizes.slice(readsBefore).reduce((total, size) => total + size, 0)).toBe(0)
        expect(boundary.writes).toBe(writesBefore)
    })

    it('serves a deleted session key until its cached row reaches the lease, then stops', async () => {
        const lifetimeMs = 60_000
        let fakeNow = 1_000
        const clock = jest.spyOn(performance, 'now').mockImplementation(() => fakeNow)
        try {
            const db = new MlKeyDynamoDB(
                boundary as unknown as DynamoDBClient,
                table,
                undefined,
                undefined,
                1000,
                lifetimeMs
            )
            const warm = new MlSessionKeyStore(db, encryption)
            const sameReader = new MlKeyReader(db, encryption)
            const location = sessionKeyId(session.teamId, session.sessionId)
            await (await warm.prepare([session])).commit()
            expect((await sameReader.read([location])).size).toBe(1)
            boundary.items.set(tableKeyString(location), { ...encodeKey(location), deleted: { BOOL: true } })
            // The read part way through must not extend the entry, or a session read often enough never observes its deletion.
            fakeNow += lifetimeMs * 0.6
            expect((await sameReader.read([location])).size).toBe(1)
            fakeNow += lifetimeMs * 0.4 + 1
            expect((await sameReader.read([location])).size).toBe(0)
        } finally {
            clock.mockRestore()
        }
    })

    it('stops serving a deleted session key to a reader that has not cached it', async () => {
        const first = await store.prepare([session])
        await first.commit()
        const blocked = sessionKeyId(session.teamId, session.sessionId)
        boundary.items.set(tableKeyString(blocked), { ...encodeKey(blocked), deleted: { BOOL: true } })
        coldCache()
        expect((await reader.read([blocked])).size).toBe(0)
        expect((await reader.read([imageKeyId(session.teamId, '2025-09')])).size).toBe(1)
    })

    it('reuses the session and monthly image keys across batches', async () => {
        const first = await store.prepare([session])
        await first.commit()
        const original = first.get(session.teamId, session.sessionId)!
        const readsBefore = boundary.readSizes.length
        const resumed = await store.prepare([session])
        const keysRead = boundary.readSizes.slice(readsBefore).reduce((total, size) => total + size, 0)
        await resumed.commit()
        const keys = resumed.get(session.teamId, session.sessionId)!
        expect(keys.session.plaintext).toEqual(original.session.plaintext)
        expect(keys.image.plaintext).toEqual(original.image.plaintext)
        expect((await reader.read([sessionKeyId(session.teamId, session.sessionId)])).size).toBe(1)
        expect(generated).toBe(1)
        // Both rows come from the cache, so a batch that repeats a session reads nothing.
        expect(keysRead).toBe(0)
    })

    it('publishes only after key writes commit and hands delivery acks to the scheduler', async () => {
        const identity = { ...session, sessionId: '01a0a4f0-3200-7000-8000-000000000001' }
        const controller = new MlKeyBatchController(store, encryption)
        const handle = new MlBatchHandle(controller)
        handle.keys = await controller.prepare([identity])
        let release!: () => void
        const delivery = new Promise<void>((resolve) => {
            release = resolve
        })
        let started = 0
        const input = {
            message: {} as Message,
            team: { teamId: identity.teamId },
            headers: { session_id: identity.sessionId },
            sessionKey: await controller.getKey(identity.sessionId, identity.teamId),
            sessionBatchRecorder: recorder,
        }
        for (let index = 0; index < 20; index++) {
            await handle.defer(input, (value) => {
                expect(
                    boundary.items.get(tableKeyString(sessionKeyId(identity.teamId, identity.sessionId)))?.sealed_key
                ).not.toBeUndefined()
                started += 1
                return Promise.resolve(ok(value, [delivery]))
            })
        }
        const scheduler = new PromiseScheduler()
        await handle.commit(recorder, scheduler)
        expect(started).toBe(20)
        expect(scheduler.promises.size).toBe(1)
        release()
        await scheduler.waitForAll()
        expect(scheduler.promises.size).toBe(0)
    })

    it('waits for delivery acks itself when no scheduler owns them', async () => {
        const identity = { ...session, sessionId: '01a0a4f0-3200-7000-8000-000000000002' }
        const controller = new MlKeyBatchController(store, encryption)
        const handle = new MlBatchHandle(controller)
        handle.keys = await controller.prepare([identity])
        let release!: () => void
        const delivery = new Promise<void>((resolve) => {
            release = resolve
        })
        const input = {
            message: {} as Message,
            team: { teamId: identity.teamId },
            headers: { session_id: identity.sessionId },
            sessionKey: await controller.getKey(identity.sessionId, identity.teamId),
            sessionBatchRecorder: recorder,
        }
        await handle.defer(input, (value) => Promise.resolve(ok(value, [delivery])))
        let committed = false
        const committing = handle.commit(recorder).then(() => {
            committed = true
        })
        await new Promise((resolve) => setImmediate(resolve))
        expect(committed).toBe(false)
        release()
        await committing
        expect(committed).toBe(true)
    })

    it('hands deferred steps the keys the commit settled on, not the ones prepared', async () => {
        const competitor = new MlSessionKeyStore(
            new MlKeyDynamoDB(boundary as unknown as DynamoDBClient, table),
            encryption
        )
        const identity = { ...session, sessionId: '01a0a4f0-3200-7000-8000-000000000004' }
        const controller = new MlKeyBatchController(store, encryption)
        const handle = new MlBatchHandle(controller)
        handle.keys = await controller.prepare([identity])
        const prepared = handle.keys.get(identity.teamId, identity.sessionId)!
        const winner = await competitor.prepare([identity])
        await winner.commit()
        const seen: Buffer[] = []
        await handle.defer(
            {
                message: {} as Message,
                team: { teamId: identity.teamId },
                headers: { session_id: identity.sessionId },
                sessionKey: await controller.getKey(identity.sessionId, identity.teamId),
                sessionBatchRecorder: recorder,
                mlKeys: prepared,
            },
            (value) => {
                seen.push(value.mlKeys!.session.plaintext, value.sessionKey.plaintextKey)
                return Promise.resolve(ok(value))
            }
        )
        jest.useFakeTimers()
        const committing = handle.commit(recorder)
        await jest.runAllTimersAsync()
        await committing
        // A sealed session key carries no KMS blob, so the plaintext is what tells the settled key from the prepared one.
        const stored = winner.get(identity.teamId, identity.sessionId)!.session.plaintext
        expect(seen).toEqual([stored, stored])
        expect(stored).not.toEqual(prepared.session.plaintext)
    })

    it('refuses to encrypt a block without the session key, because batches overlap', async () => {
        const controller = new MlKeyBatchController(store, encryption)
        await controller.prepare([session])
        await expect(controller.encryptBlock(session.sessionId, session.teamId, Buffer.alloc(4))).rejects.toThrow(
            'encryptBlockWithKey'
        )
    })

    it('reports a message once however many steps the batch defers', async () => {
        const identity = { ...session, sessionId: '01a0a4f0-3200-7000-8000-000000000005' }
        const controller = new MlKeyBatchController(store, encryption)
        const handle = new MlBatchHandle(controller)
        handle.keys = await controller.prepare([identity])
        const message = { partition: 3, offset: 9 } as unknown as Message
        const input = {
            message,
            team: { teamId: identity.teamId },
            headers: { session_id: identity.sessionId },
            sessionKey: await controller.getKey(identity.sessionId, identity.teamId),
            sessionBatchRecorder: recorder,
        }
        await handle.defer(input, (value) => Promise.resolve(ok(value)))
        await handle.defer(input, (value) => Promise.resolve(ok(value)))
        await handle.defer(input, (value) => Promise.resolve(ok(value)), true)
        expect(await handle.commit(recorder)).toEqual([message])
    })

    it('records into the recorder handed to the commit, not the one the message was fed with', async () => {
        const identity = { ...session, sessionId: '01a0a4f0-3200-7000-8000-000000000003' }
        const controller = new MlKeyBatchController(store, encryption)
        const handle = new MlBatchHandle(controller)
        handle.keys = await controller.prepare([identity])
        const flushed = { ...recorder, size: 1 } as unknown as SessionBatchRecorder
        const current = { ...recorder, size: 2 } as unknown as SessionBatchRecorder
        const input = {
            message: {} as Message,
            team: { teamId: identity.teamId },
            headers: { session_id: identity.sessionId },
            sessionKey: await controller.getKey(identity.sessionId, identity.teamId),
            sessionBatchRecorder: flushed,
        }
        const seen: SessionBatchRecorder[] = []
        await handle.defer(input, (value) => {
            seen.push(value.sessionBatchRecorder)
            return Promise.resolve(ok(value))
        })
        await handle.commit(current)
        expect(seen).toEqual([current])
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
            coldCache()
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
                    { v2: 'ml-bucket', v3: 'ml-bucket-v3' },
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
