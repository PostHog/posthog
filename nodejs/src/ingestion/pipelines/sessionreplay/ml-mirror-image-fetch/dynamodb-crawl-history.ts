import {
    AttributeValue,
    BatchGetItemCommand,
    BatchGetItemCommandOutput,
    BatchWriteItemCommand,
    BatchWriteItemCommandOutput,
    DynamoDBClient,
    WriteRequest,
} from '@aws-sdk/client-dynamodb'
import { createHash } from 'node:crypto'

import { parseJSON } from '~/common/utils/json-parse'
import { logger } from '~/common/utils/logger'

import { ConfigurationCacheItem, CrawlHistoryItem, CrawlHistoryStore } from './crawl-history'

const KEY_ATTRIBUTE = 'key'
const EXPIRES_AT_ATTRIBUTE = 'expires_at'
const VALUE_ATTRIBUTE = 'value'
const BATCH_GET_SIZE = 100
const BATCH_WRITE_SIZE = 25
const MAX_CONCURRENT_BATCH_REQUESTS = 8
const UNPROCESSED_MAX_ATTEMPTS = 5
const UNPROCESSED_INITIAL_BACKOFF_MS = 50
const ACCESS_PROBE_KEY = 'imgfetch:access-probe'
const ACCESS_PROBE_TTL_SECONDS = 5 * 60
const SAFE_ITEM_SIZE_BYTES = 350 * 1024
const BODY_CHUNK_SIZE_BYTES = 240 * 1024
const MAX_BODY_CHUNKS = 3

interface StoredBodyChunks {
    count: number
    sha256: string
}

type ParsedStoredItem =
    | { item: CrawlHistoryItem; bodyChunks?: undefined }
    | { item: ConfigurationCacheItem; bodyChunks: StoredBodyChunks }

interface ItemWritePlan {
    bodyChunkRequests: WriteRequest[]
    manifestRequest: WriteRequest
}

export type DynamoDBCrawlHistoryClient = Pick<DynamoDBClient, 'send'>

function chunk<T>(items: T[], size: number): T[][] {
    const chunks: T[][] = []
    for (let index = 0; index < items.length; index += size) {
        chunks.push(items.slice(index, index + size))
    }
    return chunks
}

function keyFromWriteRequest(request: WriteRequest): string | undefined {
    return request.PutRequest?.Item?.[KEY_ATTRIBUTE]?.S
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isFiniteNumber(value: unknown): value is number {
    return typeof value === 'number' && Number.isFinite(value)
}

function isOptionalString(value: unknown): value is string | undefined {
    return value === undefined || typeof value === 'string'
}

function isHttpCacheMetadata(value: unknown): boolean {
    if (!isRecord(value) || !isFiniteNumber(value.requestTimeMs) || !isFiniteNumber(value.responseTimeMs)) {
        return false
    }
    return ['etag', 'lastModified', 'date', 'age', 'cacheControl', 'expires'].every((field) =>
        isOptionalString(value[field])
    )
}

function isCrawlHistoryItem(value: unknown, expectedKey: string): value is CrawlHistoryItem {
    if (!isRecord(value) || value.key !== expectedKey || !isFiniteNumber(value.storageExpiresAtMs)) {
        return false
    }
    if (value.kind === 'url') {
        return (
            isFiniteNumber(value.nextFetchAtMs) &&
            typeof value.outcome === 'string' &&
            (value.cache === undefined || isHttpCacheMetadata(value.cache))
        )
    }
    return (
        (value.kind === 'robots' || value.kind === 'tdmrep') &&
        typeof value.origin === 'string' &&
        ['available', 'absent', 'refused', 'unreachable'].includes(String(value.status)) &&
        isOptionalString(value.body) &&
        isFiniteNumber(value.fetchedAtMs) &&
        isFiniteNumber(value.refreshAtMs) &&
        isFiniteNumber(value.freshUntilMs) &&
        isFiniteNumber(value.retryAtMs)
    )
}

function parseStoredItem(item: Record<string, AttributeValue>): ParsedStoredItem {
    const key = item[KEY_ATTRIBUTE]?.S
    const expiresAtSeconds = Number(item[EXPIRES_AT_ATTRIBUTE]?.N)
    if (!key || !Number.isFinite(expiresAtSeconds)) {
        throw new Error('DynamoDB returned a malformed crawl-history item')
    }
    const serialized = item[VALUE_ATTRIBUTE]?.S
    if (!serialized) {
        return {
            item: {
                kind: 'url',
                key,
                nextFetchAtMs: expiresAtSeconds * 1000,
                storageExpiresAtMs: expiresAtSeconds * 1000,
                outcome: 'legacy',
            },
        }
    }
    const parsed = parseJSON(serialized)
    if (!isRecord(parsed)) {
        throw new Error('DynamoDB returned an invalid crawl-history value')
    }
    const storedBodyChunks = parsed._bodyChunks
    if (storedBodyChunks === undefined) {
        if (!isCrawlHistoryItem(parsed, key)) {
            throw new Error('DynamoDB returned an invalid crawl-history value')
        }
        return { item: parsed }
    }
    const { _bodyChunks: _storedBodyChunks, ...applicationItem } = parsed
    if (
        !isCrawlHistoryItem(applicationItem, key) ||
        applicationItem.kind === 'url' ||
        applicationItem.body !== undefined ||
        !isRecord(storedBodyChunks) ||
        !Number.isInteger(storedBodyChunks.count) ||
        (storedBodyChunks.count as number) < 1 ||
        (storedBodyChunks.count as number) > MAX_BODY_CHUNKS ||
        typeof storedBodyChunks.sha256 !== 'string' ||
        !/^[0-9a-f]{64}$/.test(storedBodyChunks.sha256)
    ) {
        throw new Error('DynamoDB returned invalid crawl-history body chunks')
    }
    return {
        item: applicationItem,
        bodyChunks: { count: storedBodyChunks.count as number, sha256: storedBodyChunks.sha256 },
    }
}

function bodyChunkKey(key: string, sha256: string, index: number): string {
    return `${key}:body:${sha256}:${index}`
}

function putRequest(key: string, storageExpiresAtMs: number, serialized: string): WriteRequest {
    const expiresAt = String(Math.ceil(storageExpiresAtMs / 1000))
    const sizeBytes =
        Buffer.byteLength(KEY_ATTRIBUTE) +
        Buffer.byteLength(key) +
        Buffer.byteLength(EXPIRES_AT_ATTRIBUTE) +
        Buffer.byteLength(expiresAt) +
        Buffer.byteLength(VALUE_ATTRIBUTE) +
        Buffer.byteLength(serialized)
    if (sizeBytes > SAFE_ITEM_SIZE_BYTES) {
        throw new Error(`crawl-history item ${key} exceeds the safe DynamoDB item size`)
    }
    return {
        PutRequest: {
            Item: {
                [KEY_ATTRIBUTE]: { S: key },
                [EXPIRES_AT_ATTRIBUTE]: { N: expiresAt },
                [VALUE_ATTRIBUTE]: { S: serialized },
            },
        },
    }
}

function writePlanForItem(item: CrawlHistoryItem): ItemWritePlan {
    const serialized = JSON.stringify(item)
    if (Buffer.byteLength(serialized) <= SAFE_ITEM_SIZE_BYTES / 2 || item.kind === 'url' || !item.body) {
        return {
            bodyChunkRequests: [],
            manifestRequest: putRequest(item.key, item.storageExpiresAtMs, serialized),
        }
    }
    const body = Buffer.from(item.body, 'utf8')
    const bodyChunks: Buffer[] = []
    for (let offset = 0; offset < body.length; offset += BODY_CHUNK_SIZE_BYTES) {
        bodyChunks.push(body.subarray(offset, offset + BODY_CHUNK_SIZE_BYTES))
    }
    if (bodyChunks.length > MAX_BODY_CHUNKS) {
        throw new Error(`crawl-history body ${item.key} needs too many DynamoDB items`)
    }
    const sha256 = createHash('sha256').update(body).digest('hex')
    const storedItem = {
        ...item,
        body: undefined,
        _bodyChunks: {
            count: bodyChunks.length,
            sha256,
        },
    }
    return {
        bodyChunkRequests: bodyChunks.map((bodyChunk, index) =>
            putRequest(bodyChunkKey(item.key, sha256, index), item.storageExpiresAtMs, bodyChunk.toString('base64'))
        ),
        manifestRequest: putRequest(item.key, item.storageExpiresAtMs, JSON.stringify(storedItem)),
    }
}

export class DynamoDBCrawlHistory implements CrawlHistoryStore {
    constructor(
        private readonly client: DynamoDBCrawlHistoryClient,
        private readonly tableName: string,
        private readonly commandTimeoutMs: number,
        private readonly batchBudgetMs: number
    ) {}

    public async validateAccess(nowMs: number): Promise<void> {
        const expiresAt = Math.floor(nowMs / 1000) + ACCESS_PROBE_TTL_SECONDS
        const writeResponse = await this.sendBatchWrite(
            new BatchWriteItemCommand({
                RequestItems: {
                    [this.tableName]: [
                        {
                            PutRequest: {
                                Item: {
                                    [KEY_ATTRIBUTE]: { S: ACCESS_PROBE_KEY },
                                    [EXPIRES_AT_ATTRIBUTE]: { N: String(expiresAt) },
                                },
                            },
                        },
                    ],
                },
            })
        )
        if ((writeResponse.UnprocessedItems?.[this.tableName] ?? []).length > 0) {
            throw new Error('DynamoDB crawl-history access probe write was not processed')
        }
        const readResponse = await this.sendBatchGet(
            new BatchGetItemCommand({
                RequestItems: {
                    [this.tableName]: {
                        Keys: [{ [KEY_ATTRIBUTE]: { S: ACCESS_PROBE_KEY } }],
                        ProjectionExpression: '#key',
                        ExpressionAttributeNames: { '#key': KEY_ATTRIBUTE },
                        ConsistentRead: true,
                    },
                },
            })
        )
        if (
            (readResponse.UnprocessedKeys?.[this.tableName]?.Keys ?? []).length > 0 ||
            !(readResponse.Responses?.[this.tableName] ?? []).some(
                (item) => item[KEY_ATTRIBUTE]?.S === ACCESS_PROBE_KEY
            )
        ) {
            throw new Error('DynamoDB crawl-history access probe read was not processed')
        }
    }

    public async read(keys: string[]): Promise<Map<string, CrawlHistoryItem>> {
        const result = new Map<string, CrawlHistoryItem>()
        const startedAt = process.hrtime.bigint()
        const bodyChunks = new Map<string, { item: ConfigurationCacheItem; metadata: StoredBodyChunks }>()
        for (const item of await this.readRawItems([...new Set(keys)], startedAt)) {
            const parsed = parseStoredItem(item)
            if (parsed.bodyChunks) {
                bodyChunks.set(parsed.item.key, { item: parsed.item, metadata: parsed.bodyChunks })
            } else {
                result.set(parsed.item.key, parsed.item)
            }
        }
        if (bodyChunks.size === 0) {
            return result
        }

        const chunkKeys = [...bodyChunks].flatMap(([key, value]) =>
            Array.from({ length: value.metadata.count }, (_unused, index) =>
                bodyChunkKey(key, value.metadata.sha256, index)
            )
        )
        const encodedChunks = new Map<string, string>()
        for (const item of await this.readRawItems(chunkKeys, startedAt)) {
            const key = item[KEY_ATTRIBUTE]?.S
            const encoded = item[VALUE_ATTRIBUTE]?.S
            if (!key || !encoded) {
                logger.warn('🌐', 'ml_image_fetch_crawl_history_chunk_invalid', { key: key ?? 'missing' })
                continue
            }
            encodedChunks.set(key, encoded)
        }
        for (const [key, value] of bodyChunks) {
            try {
                const chunks = Array.from({ length: value.metadata.count }, (_unused, index) => {
                    const encoded = encodedChunks.get(bodyChunkKey(key, value.metadata.sha256, index))
                    if (!encoded) {
                        throw new Error('missing')
                    }
                    const decoded = Buffer.from(encoded, 'base64')
                    if (decoded.toString('base64') !== encoded) {
                        throw new Error('invalid base64')
                    }
                    return decoded
                })
                const body = Buffer.concat(chunks)
                if (createHash('sha256').update(body).digest('hex') !== value.metadata.sha256) {
                    throw new Error('checksum mismatch')
                }
                result.set(key, { ...value.item, body: new TextDecoder('utf-8', { fatal: true }).decode(body) })
            } catch (error) {
                logger.warn('🌐', 'ml_image_fetch_crawl_history_chunk_incomplete', {
                    key,
                    error: String(error),
                })
            }
        }
        return result
    }

    private async readRawItems(keys: string[], startedAt: bigint): Promise<Record<string, AttributeValue>[]> {
        const result: Record<string, AttributeValue>[] = []
        await this.runChunks(chunk(keys, BATCH_GET_SIZE), async (batch) => {
            let pending = batch
            for (let attempt = 1; pending.length > 0; attempt++) {
                this.requireBudget(startedAt)
                const response = await this.sendBatchGet(
                    new BatchGetItemCommand({
                        RequestItems: {
                            [this.tableName]: {
                                Keys: pending.map((key) => ({ [KEY_ATTRIBUTE]: { S: key } })),
                                ProjectionExpression: '#key, #expiresAt, #value',
                                ExpressionAttributeNames: {
                                    '#key': KEY_ATTRIBUTE,
                                    '#expiresAt': EXPIRES_AT_ATTRIBUTE,
                                    '#value': VALUE_ATTRIBUTE,
                                },
                            },
                        },
                    })
                )
                for (const item of response.Responses?.[this.tableName] ?? []) {
                    result.push(item)
                }
                pending = (response.UnprocessedKeys?.[this.tableName]?.Keys ?? []).flatMap((key) =>
                    key[KEY_ATTRIBUTE]?.S ? [key[KEY_ATTRIBUTE].S] : []
                )
                if (pending.length > 0) {
                    if (attempt >= UNPROCESSED_MAX_ATTEMPTS) {
                        throw new Error(`DynamoDB left ${pending.length} crawl-history reads unprocessed`)
                    }
                    await this.backoffBeforeRetry(attempt)
                }
            }
        })
        return result
    }

    public async write(items: CrawlHistoryItem[]): Promise<void> {
        const byKey = new Map(items.map((item) => [item.key, item]))
        const plans = [...byKey.values()].map(writePlanForItem)
        const startedAt = process.hrtime.bigint()
        await this.writeRequests(
            plans.flatMap((plan) => plan.bodyChunkRequests),
            startedAt
        )
        await this.writeRequests(
            plans.map((plan) => plan.manifestRequest),
            startedAt
        )
    }

    private async writeRequests(requests: WriteRequest[], startedAt: bigint): Promise<void> {
        await this.runChunks(chunk(requests, BATCH_WRITE_SIZE), async (batch) => {
            let pending = batch
            for (let attempt = 1; pending.length > 0; attempt++) {
                this.requireBudget(startedAt)
                const response = await this.sendBatchWrite(
                    new BatchWriteItemCommand({ RequestItems: { [this.tableName]: pending } })
                )
                pending = response.UnprocessedItems?.[this.tableName] ?? []
                if (pending.length > 0) {
                    if (attempt >= UNPROCESSED_MAX_ATTEMPTS) {
                        const keys = pending.flatMap((request) => keyFromWriteRequest(request) ?? [])
                        throw new Error(`DynamoDB left crawl-history writes unprocessed: ${keys.join(',')}`)
                    }
                    await this.backoffBeforeRetry(attempt)
                }
            }
        })
    }

    private async runChunks<T>(chunks: T[][], run: (batch: T[]) => Promise<void>): Promise<void> {
        let nextChunk = 0
        const worker = async (): Promise<void> => {
            while (nextChunk < chunks.length) {
                await run(chunks[nextChunk++])
            }
        }
        await Promise.all(Array.from({ length: Math.min(chunks.length, MAX_CONCURRENT_BATCH_REQUESTS) }, worker))
    }

    private requireBudget(startedAt: bigint): void {
        if (Number(process.hrtime.bigint() - startedAt) / 1e6 > this.batchBudgetMs) {
            throw new Error('DynamoDB crawl-history batch budget was exhausted')
        }
    }

    private async backoffBeforeRetry(attempt: number): Promise<void> {
        const maximumDelayMs = UNPROCESSED_INITIAL_BACKOFF_MS * 2 ** (attempt - 1)
        const delayMs = Math.floor(maximumDelayMs / 2 + Math.random() * (maximumDelayMs / 2))
        await new Promise<void>((resolve) => setTimeout(resolve, delayMs))
    }

    private sendBatchGet(command: BatchGetItemCommand): Promise<BatchGetItemCommandOutput> {
        return this.withTimeout((abortSignal) => this.client.send(command, { abortSignal }))
    }

    private sendBatchWrite(command: BatchWriteItemCommand): Promise<BatchWriteItemCommandOutput> {
        return this.withTimeout((abortSignal) => this.client.send(command, { abortSignal }))
    }

    private async withTimeout<T>(send: (abortSignal: AbortSignal) => Promise<T>): Promise<T> {
        const abortController = new AbortController()
        const timer = setTimeout(() => abortController.abort(), this.commandTimeoutMs)
        timer.unref()
        try {
            return await send(abortController.signal)
        } finally {
            clearTimeout(timer)
        }
    }
}
