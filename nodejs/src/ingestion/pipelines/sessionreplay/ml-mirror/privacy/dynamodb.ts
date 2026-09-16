import {
    AttributeValue,
    BatchGetItemCommand,
    ConditionalCheckFailedException,
    DynamoDBClient,
    PutItemCommand,
} from '@aws-sdk/client-dynamodb'
import pLimit from 'p-limit'

import { MlMirrorMetrics, MlPrivacyRequest } from '~/ingestion/pipelines/sessionreplay/ml-mirror/metrics'

import { TableKey, tableKeyString } from './schema'

export type DynamoItem = Record<string, AttributeValue>

export function encodeKey(key: TableKey): DynamoItem {
    return { pk: { S: key.pk }, sk: { S: key.sk } }
}

export function decodeKey(item: DynamoItem): TableKey {
    if (!item.pk?.S || !item.sk?.S) {
        throw new Error('Invalid ML privacy item key')
    }
    return { pk: item.pk.S, sk: item.sk.S }
}

export class MlPrivacyDynamoDB {
    private readonly concurrency = pLimit(4)
    private readonly writeConcurrency = pLimit(32)

    constructor(
        private readonly client: Pick<DynamoDBClient, 'send'>,
        readonly tableName: string,
        private readonly requestTimeoutMs = 5_000,
        private readonly attempts = 5
    ) {}

    public async read(keys: TableKey[], deadline?: AbortSignal): Promise<Map<string, DynamoItem>> {
        return this.timed('dynamodb_read', () => this.readUntimed(keys, deadline))
    }

    private async readUntimed(keys: TableKey[], deadline?: AbortSignal): Promise<Map<string, DynamoItem>> {
        const unique = [...new Map(keys.map((key) => [tableKeyString(key), key])).values()]
        const result = new Map<string, DynamoItem>()
        const chunks: TableKey[][] = []
        for (let offset = 0; offset < unique.length; offset += 100) {
            chunks.push(unique.slice(offset, offset + 100))
        }
        await Promise.all(
            chunks.map((chunk) =>
                this.concurrency(async () => {
                    let pending = chunk.map(encodeKey)
                    for (let attempt = 0; pending.length && attempt < this.attempts; attempt++) {
                        const response = await this.client.send(
                            new BatchGetItemCommand({
                                RequestItems: { [this.tableName]: { Keys: pending, ConsistentRead: true } },
                            }),
                            { abortSignal: this.requestSignal(deadline) }
                        )
                        for (const item of response.Responses?.[this.tableName] ?? []) {
                            result.set(tableKeyString(decodeKey(item)), item)
                        }
                        pending = response.UnprocessedKeys?.[this.tableName]?.Keys ?? []
                        if (pending.length) {
                            await this.backoff(attempt)
                        }
                    }
                    if (pending.length) {
                        throw new Error('ML privacy bulk read exhausted retries')
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

    private async timed<T>(request: MlPrivacyRequest, operation: () => Promise<T>): Promise<T> {
        const startedAt = performance.now()
        try {
            return await operation()
        } finally {
            MlMirrorMetrics.observeMlPrivacyRequest(request, performance.now() - startedAt)
        }
    }

    private requestSignal(deadline?: AbortSignal): AbortSignal {
        const timeout = AbortSignal.timeout(this.requestTimeoutMs)
        return deadline ? AbortSignal.any([deadline, timeout]) : timeout
    }

    public async backoff(attempt: number): Promise<void> {
        await new Promise((resolve) => setTimeout(resolve, Math.min(1000, 50 * 2 ** attempt) + Math.random() * 50))
    }
}
