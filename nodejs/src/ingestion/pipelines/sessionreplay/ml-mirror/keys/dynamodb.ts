import {
    AttributeValue,
    BatchGetItemCommand,
    ConditionalCheckFailedException,
    DynamoDBClient,
    PutItemCommand,
} from '@aws-sdk/client-dynamodb'
import { LRUCache } from 'lru-cache'
import pLimit from 'p-limit'

import { MlKeyRequest, MlMirrorMetrics } from '~/ingestion/pipelines/sessionreplay/ml-mirror/metrics'

import { TableKey, tableKeyString } from './schema'
import { isTransientError } from './transient'

export type DynamoItem = Record<string, AttributeValue>

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

    constructor(
        private readonly client: Pick<DynamoDBClient, 'send'>,
        readonly tableName: string,
        private readonly requestTimeoutMs = 5_000,
        private readonly attempts = 10,
        cacheMax = 100_000,
        cacheLifetimeMs = 1_800_000
    ) {
        this.rows = new LRUCache({ max: cacheMax, ttl: cacheLifetimeMs })
    }

    // Only a usable key row is stable enough to cache, because putIfAbsent writes it once. A team block row decides
    // whether a batch may mint new keys, so a stale absent one would write durable keys for a team that asked to be blocked.
    private cacheable(key: TableKey): boolean {
        return key.sk.startsWith('session:') || key.sk.startsWith('image:')
    }

    public async read(keys: TableKey[], deadline?: AbortSignal): Promise<Map<string, DynamoItem>> {
        const unique = [...new Map(keys.map((key) => [tableKeyString(key), key])).values()]
        const result = new Map<string, DynamoItem>()
        const missing: TableKey[] = []
        for (const key of unique) {
            const id = tableKeyString(key)
            const cached = this.cacheable(key) ? this.rows.get(id) : undefined
            if (cached) {
                result.set(id, cached)
            } else {
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
                            if (!isTransientError(error) || deadline?.aborted || attempt === this.attempts - 1) {
                                throw error
                            }
                            await this.backoff(attempt, deadline)
                            continue
                        }
                        for (const item of response.Responses?.[this.tableName] ?? []) {
                            const key = decodeKey(item)
                            const id = tableKeyString(key)
                            result.set(id, item)
                            if (!this.cacheable(key)) {
                                continue
                            }
                            if (item.wrapped_key?.B && item.deleted?.BOOL !== true) {
                                this.rows.set(id, item)
                            } else {
                                this.rows.delete(id)
                            }
                        }
                        pending = response.UnprocessedKeys?.[this.tableName]?.Keys ?? []
                        if (pending.length) {
                            await this.backoff(attempt, deadline)
                        }
                    }
                    if (pending.length) {
                        throw new Error('ML key manager bulk read exhausted retries')
                    }
                })
            )
        )
        return result
    }

    public async putIfAbsent(key: TableKey, attributes: DynamoItem, deadline?: AbortSignal): Promise<boolean> {
        return this.writeConcurrency(() =>
            this.timed('dynamodb_put_if_absent', async () => {
                try {
                    await this.client.send(
                        new PutItemCommand({
                            TableName: this.tableName,
                            Item: { ...encodeKey(key), ...attributes },
                            ConditionExpression: 'attribute_not_exists(pk)',
                        }),
                        { abortSignal: this.requestSignal(deadline) }
                    )
                    return true
                } catch (error) {
                    if (error instanceof ConditionalCheckFailedException) {
                        return false
                    }
                    throw error
                }
            })
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
