import {
    AttributeValue,
    BatchGetItemCommand,
    BatchWriteItemCommand,
    ConditionalCheckFailedException,
    DynamoDBClient,
    PutItemCommand,
} from '@aws-sdk/client-dynamodb'
import { LRUCache } from 'lru-cache'
import pLimit from 'p-limit'

import { MlKeyRequest, MlMirrorMetrics } from '~/ingestion/pipelines/sessionreplay/ml-mirror/metrics'

import { TableKey, holdsCacheableRow, storedSessionId, tableKeyString } from './schema'
import { isTransientError } from './transient'

// A shred removes the durable key, so a process that runs on a held row writes data that no reader can open, and a
// lifetime here trades re-reads against how long that lasts. A team row is one row per team per month, so it is held
// longer for far fewer reads. Both kinds cover their tombstones too. See products/ai_training/docs/replay-data.md.
const SESSION_ROW_MAX_LIFETIME_MS = 300_000
const TEAM_ROW_LIFETIME_MS = 3_600_000
// Neither caller passes a deadline, and max.poll.interval.ms is 300s, so the retry loop needs a bound of its own.
const READ_BUDGET_MS = 30_000

export type DynamoItem = Record<string, AttributeValue>

// config.ts parses an env value with parseFloat, so a typo arrives as NaN or a fraction. Refusing to start names the
// setting, where a fallback would run with a lifetime the operator did not choose and never say so.
function positiveInteger(value: number, setting: string, cap = Number.MAX_SAFE_INTEGER): number {
    if (!Number.isSafeInteger(value) || value <= 0) {
        throw new Error(`${setting} must be a positive integer, got ${value}`)
    }
    return Math.min(value, cap)
}

// The SDK returns byte views over Node's shared 8 KiB pool, so holding one keeps the whole slab. The freeze is top level.
function detachedRow(item: DynamoItem): DynamoItem {
    const copy: DynamoItem = {}
    for (const [name, value] of Object.entries(item)) {
        copy[name] = value.B ? Object.freeze({ ...value, B: Uint8Array.from(value.B) }) : value
    }
    return Object.freeze(copy)
}

export function encodeKey(key: TableKey): DynamoItem {
    return { pk: { S: key.pk }, sk: { S: key.sk } }
}

export function decodeKey(item: DynamoItem): TableKey {
    if (!item.pk?.S || !item.sk?.S) {
        throw new Error('Invalid ML key manager item key')
    }
    return { pk: item.pk.S, sk: item.sk.S }
}

export class MlKeyDynamoDB {
    private readonly concurrency = pLimit(4)
    private readonly writeConcurrency = pLimit(32)
    private readonly rows: LRUCache<string, DynamoItem>
    private readonly sessionRowLifetimeMs: number

    constructor(
        private readonly client: Pick<DynamoDBClient, 'send'>,
        readonly tableName: string,
        private readonly requestTimeoutMs = 5_000,
        private readonly attempts = 6,
        cacheMax = 100_000,
        cacheLifetimeMs = SESSION_ROW_MAX_LIFETIME_MS
    ) {
        this.sessionRowLifetimeMs = positiveInteger(
            cacheLifetimeMs,
            'AI_RESEARCH_REPLAY_ROW_CACHE_LIFETIME_MS',
            SESSION_ROW_MAX_LIFETIME_MS
        )
        this.rows = new LRUCache({
            max: positiveInteger(cacheMax, 'AI_RESEARCH_REPLAY_ROW_CACHE_MAX'),
            ttl: this.sessionRowLifetimeMs,
            // lru-cache otherwise reads the clock once and refreshes it from a timer, so a loop that stays on
            // microtasks keeps serving a row past the lease. This TTL carries the deletion lease, so it reads exactly.
            ttlResolution: 0,
        })
    }

    // Only a usable key row is stable enough to cache, because putIfAbsent writes it once.
    private cacheable(key: TableKey): boolean {
        return holdsCacheableRow(key)
    }

    private hold(key: TableKey, item: DynamoItem): void {
        if (!this.cacheable(key)) {
            return
        }
        const id = tableKeyString(key)
        const usable = item.deleted?.BOOL === true || item.wrapped_key?.B || (item.sealed_key?.B && item.key_nonce?.B)
        if (!usable) {
            // No key and no tombstone is a row that repair can still fill in.
            this.rows.delete(id)
            return
        }
        this.rows.set(id, detachedRow(item), {
            ttl: storedSessionId(key.sk) ? this.sessionRowLifetimeMs : TEAM_ROW_LIFETIME_MS,
        })
    }

    public async read(keys: TableKey[], callerDeadline?: AbortSignal): Promise<Map<string, DynamoItem>> {
        const deadline = callerDeadline ?? AbortSignal.timeout(READ_BUDGET_MS)
        const unique = [...new Map(keys.map((key) => [tableKeyString(key), key])).values()]
        const result = new Map<string, DynamoItem>()
        const missing: TableKey[] = []
        for (const key of unique) {
            const id = tableKeyString(key)
            const cached = this.cacheable(key) ? this.rows.get(id) : undefined
            if (cached) {
                MlMirrorMetrics.incrementMlKeyRowCacheLookup('hit')
                result.set(id, cached)
            } else {
                if (this.cacheable(key)) {
                    MlMirrorMetrics.incrementMlKeyRowCacheLookup('miss')
                }
                missing.push(key)
            }
        }
        const chunks: TableKey[][] = []
        for (let offset = 0; offset < missing.length; offset += 100) {
            chunks.push(missing.slice(offset, offset + 100))
        }
        await Promise.all(
            chunks.map((chunk) =>
                this.concurrency(async () => {
                    let pending = chunk.map(encodeKey)
                    for (let attempt = 0; pending.length && attempt < this.attempts; attempt++) {
                        // Reads retry here because MlKeyReader and MlSessionKeyStore.prepare have no retry of their own, unlike writes, which MlKeyBatch.commit retries.
                        let response
                        try {
                            response = await this.timed('dynamodb_read', () =>
                                this.client.send(
                                    new BatchGetItemCommand({
                                        RequestItems: { [this.tableName]: { Keys: pending, ConsistentRead: true } },
                                    }),
                                    { abortSignal: this.requestSignal(deadline) }
                                )
                            )
                        } catch (error) {
                            // A spent deadline also aborts the request, and an AbortError counts as transient, so the
                            // deadline is checked separately. Otherwise the loop waits out its attempts past the budget
                            // that keeps a batch under the consumer's stall threshold.
                            if (!isTransientError(error) || deadline.aborted || attempt === this.attempts - 1) {
                                throw error
                            }
                            MlMirrorMetrics.incrementMlKeyReadRetry('transient_error')
                            await this.backoff(attempt, deadline)
                            if (deadline.aborted) {
                                throw new DOMException('ML key manager bulk read deadline expired', 'AbortError')
                            }
                            continue
                        }
                        for (const item of response.Responses?.[this.tableName] ?? []) {
                            const key = decodeKey(item)
                            const id = tableKeyString(key)
                            result.set(id, item)
                            this.hold(key, item)
                        }
                        pending = response.UnprocessedKeys?.[this.tableName]?.Keys ?? []
                        if (pending.length) {
                            MlMirrorMetrics.incrementMlKeyReadRetry('unprocessed_keys')
                            await this.backoff(attempt, deadline)
                            if (deadline.aborted) {
                                throw new DOMException('ML key manager bulk read deadline expired', 'AbortError')
                            }
                        }
                    }
                    if (pending.length) {
                        throw new Error('ML key manager bulk read exhausted retries')
                    }
                })
            )
        )
        this.rows.purgeStale()
        MlMirrorMetrics.setMlKeyRowCacheEntries(this.rows.size)
        return result
    }

    public clear(): void {
        this.rows.clear()
        MlMirrorMetrics.setMlKeyRowCacheEntries(0)
    }

    /** Resolves to the row that won when this put lost, or to undefined when this put stored the key. */
    public async putIfAbsent(
        key: TableKey,
        attributes: DynamoItem,
        deadline?: AbortSignal
    ): Promise<DynamoItem | undefined> {
        const outcome = await this.writeConcurrency(() =>
            this.timed('dynamodb_put_if_absent', async () => {
                try {
                    await this.client.send(
                        new PutItemCommand({
                            TableName: this.tableName,
                            Item: { ...encodeKey(key), ...attributes },
                            ConditionExpression: 'attribute_not_exists(pk)',
                            // The refusal carries the row that won, so the loser needs no read to adopt it.
                            ReturnValuesOnConditionCheckFailure: 'ALL_OLD',
                        }),
                        { abortSignal: this.requestSignal(deadline) }
                    )
                    // This row now exists with exactly these attributes, so the next batch needs no read for it.
                    this.hold(key, { ...encodeKey(key), ...attributes })
                    return { created: true, winner: undefined }
                } catch (error) {
                    if (error instanceof ConditionalCheckFailedException) {
                        return { created: false, winner: error.Item }
                    }
                    throw error
                }
            })
        )
        if (outcome.created) {
            return undefined
        }
        if (outcome.winner) {
            this.hold(key, outcome.winner)
            return outcome.winner
        }
        // An endpoint that refuses the put without returning the row leaves the winner unknown. Reading it costs one
        // request on a conflict and keeps the caller from reading an absent key as an unusable one.
        return (await this.read([key], deadline)).get(tableKeyString(key)) ?? {}
    }

    /** Writes rows that need no condition, 25 to a request, so a key costs one write request rather than two. */
    public async putMany(rows: Array<{ key: TableKey; attributes: DynamoItem }>, deadline: AbortSignal): Promise<void> {
        const chunks: (typeof rows)[] = []
        for (let offset = 0; offset < rows.length; offset += 25) {
            chunks.push(rows.slice(offset, offset + 25))
        }
        await Promise.all(
            chunks.map((chunk) =>
                this.writeConcurrency(async () => {
                    let pending = chunk.map(({ key, attributes }) => ({
                        PutRequest: { Item: { ...encodeKey(key), ...attributes } },
                    }))
                    for (let attempt = 0; pending.length && attempt < this.attempts; attempt++) {
                        let response
                        try {
                            response = await this.timed('dynamodb_put_batch', () =>
                                this.client.send(
                                    new BatchWriteItemCommand({ RequestItems: { [this.tableName]: pending } }),
                                    { abortSignal: this.requestSignal(deadline) }
                                )
                            )
                        } catch (error) {
                            if (!isTransientError(error) || deadline.aborted || attempt === this.attempts - 1) {
                                throw error
                            }
                            await this.backoff(attempt, deadline)
                            if (deadline.aborted) {
                                throw error
                            }
                            continue
                        }
                        pending = (response.UnprocessedItems?.[this.tableName] ?? []) as typeof pending
                        if (pending.length) {
                            await this.backoff(attempt, deadline)
                            if (deadline.aborted) {
                                throw new DOMException('ML key manager index write deadline expired', 'AbortError')
                            }
                        }
                    }
                    if (pending.length) {
                        throw new Error('ML key manager index write exhausted retries')
                    }
                })
            )
        )
    }

    public async put(key: TableKey, attributes: DynamoItem, deadline?: AbortSignal): Promise<void> {
        await this.writeConcurrency(() =>
            this.timed('dynamodb_put', () =>
                this.client.send(
                    new PutItemCommand({ TableName: this.tableName, Item: { ...encodeKey(key), ...attributes } }),
                    { abortSignal: this.requestSignal(deadline) }
                )
            )
        )
    }

    private async timed<T>(request: MlKeyRequest, operation: () => Promise<T>): Promise<T> {
        const startedAt = performance.now()
        try {
            return await operation()
        } finally {
            MlMirrorMetrics.observeMlKeyRequest(request, performance.now() - startedAt)
        }
    }

    private requestSignal(deadline?: AbortSignal): AbortSignal {
        const timeout = AbortSignal.timeout(this.requestTimeoutMs)
        return deadline ? AbortSignal.any([deadline, timeout]) : timeout
    }

    // The cap matches MlKeyBatch.commit because an account-wide throttle outlasts a shorter budget.
    public async backoff(attempt: number, deadline?: AbortSignal): Promise<void> {
        const delayMs = Math.min(3_000, 50 * 2 ** attempt) + Math.random() * 50
        if (!deadline) {
            await new Promise((resolve) => setTimeout(resolve, delayMs))
            return
        }
        if (deadline.aborted) {
            return
        }
        await new Promise<void>((resolve) => {
            const stop = (): void => {
                clearTimeout(timer)
                deadline.removeEventListener('abort', stop)
                resolve()
            }
            const timer = setTimeout(stop, delayMs)
            deadline.addEventListener('abort', stop, { once: true })
        })
    }
}
