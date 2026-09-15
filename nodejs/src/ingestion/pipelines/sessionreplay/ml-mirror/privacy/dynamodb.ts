import {
    AttributeValue,
    BatchGetItemCommand,
    DynamoDBClient,
    TransactWriteItem,
    TransactWriteItemsCommand,
} from '@aws-sdk/client-dynamodb'
import pLimit from 'p-limit'

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

    constructor(
        private readonly client: Pick<DynamoDBClient, 'send'>,
        readonly tableName: string,
        private readonly requestTimeoutMs = 5_000,
        private readonly attempts = 5
    ) {}

    public async read(keys: TableKey[]): Promise<Map<string, DynamoItem>> {
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
                            { abortSignal: AbortSignal.timeout(this.requestTimeoutMs) }
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

    public async write(transactions: TransactWriteItem[][]): Promise<void> {
        await Promise.all(
            transactions.map((items) =>
                this.concurrency(async () => {
                    if (!items.length || items.length > 100) {
                        throw new Error('Invalid ML privacy transaction size')
                    }
                    await this.client.send(new TransactWriteItemsCommand({ TransactItems: items }), {
                        abortSignal: AbortSignal.timeout(this.requestTimeoutMs),
                    })
                })
            )
        )
    }

    public async backoff(attempt: number): Promise<void> {
        await new Promise((resolve) => setTimeout(resolve, Math.min(1000, 50 * 2 ** attempt) + Math.random() * 50))
    }

    public check(key: TableKey, condition: string, values?: DynamoItem): TransactWriteItem {
        return {
            ConditionCheck: {
                TableName: this.tableName,
                Key: encodeKey(key),
                ConditionExpression: condition,
                ...(values ? { ExpressionAttributeValues: values } : {}),
            },
        }
    }
}
