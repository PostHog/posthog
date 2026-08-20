import {
    BatchGetItemCommand,
    BatchGetItemCommandOutput,
    BatchWriteItemCommand,
    BatchWriteItemCommandOutput,
    DynamoDBClient,
    WriteRequest,
} from '@aws-sdk/client-dynamodb'

import { CrawlHistoryReadResult, CrawlHistoryStore } from './crawl-history'

const KEY_ATTRIBUTE = 'key'
const EXPIRES_AT_ATTRIBUTE = 'expires_at'
const BATCH_GET_SIZE = 100
const BATCH_WRITE_SIZE = 25
const MAX_CONCURRENT_BATCH_REQUESTS = 8
const UNPROCESSED_MAX_ATTEMPTS = 5
const UNPROCESSED_INITIAL_BACKOFF_MS = 50
const ACCESS_PROBE_KEY = 'imgfetch:access-probe'
const ACCESS_PROBE_TTL_SECONDS = 5 * 60

export type DynamoDBCrawlHistoryClient = Pick<DynamoDBClient, 'send'>

function chunk<T>(items: T[], size: number): T[][] {
    const chunks: T[][] = []
    for (let index = 0; index < items.length; index += size) {
        chunks.push(items.slice(index, index + size))
    }
    return chunks
}

function indexKeys(keys: string[]): Map<string, number[]> {
    const indexesByKey = new Map<string, number[]>()
    keys.forEach((key, index) => {
        const indexes = indexesByKey.get(key) ?? []
        indexes.push(index)
        indexesByKey.set(key, indexes)
    })
    return indexesByKey
}

function addIndexes(target: Set<number>, keys: string[], indexesByKey: Map<string, number[]>): void {
    for (const key of keys) {
        for (const index of indexesByKey.get(key) ?? []) {
            target.add(index)
        }
    }
}

function keysFromWriteRequests(requests: WriteRequest[]): string[] {
    return requests.flatMap((request) => {
        const key = request.PutRequest?.Item?.[KEY_ATTRIBUTE]?.S
        return key ? [key] : []
    })
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
        const readWasUnprocessed = (readResponse.UnprocessedKeys?.[this.tableName]?.Keys ?? []).length > 0
        const probeWasRead = (readResponse.Responses?.[this.tableName] ?? []).some(
            (item) => item[KEY_ATTRIBUTE]?.S === ACCESS_PROBE_KEY
        )
        if (readWasUnprocessed || !probeWasRead) {
            throw new Error('DynamoDB crawl-history access probe read was not processed')
        }
    }

    public async read(keys: string[], nowMs: number): Promise<CrawlHistoryReadResult> {
        const known = new Set<number>()
        const failed = new Set<number>()
        const indexesByKey = indexKeys(keys)
        const uniqueKeys = [...indexesByKey.keys()]
        const startedAt = process.hrtime.bigint()
        const nowSeconds = Math.floor(nowMs / 1000)

        await this.runChunks(chunk(uniqueKeys, BATCH_GET_SIZE), async (batch) => {
            let pending = batch
            for (let attempt = 1; attempt <= UNPROCESSED_MAX_ATTEMPTS; attempt++) {
                if (this.batchBudgetSpent(startedAt)) {
                    addIndexes(failed, pending, indexesByKey)
                    return
                }

                let response: BatchGetItemCommandOutput
                try {
                    response = await this.sendBatchGet(
                        new BatchGetItemCommand({
                            RequestItems: {
                                [this.tableName]: {
                                    Keys: pending.map((key) => ({ [KEY_ATTRIBUTE]: { S: key } })),
                                    ProjectionExpression: '#key, #expiresAt',
                                    ExpressionAttributeNames: {
                                        '#key': KEY_ATTRIBUTE,
                                        '#expiresAt': EXPIRES_AT_ATTRIBUTE,
                                    },
                                },
                            },
                        })
                    )
                } catch {
                    addIndexes(failed, pending, indexesByKey)
                    return
                }

                for (const item of response.Responses?.[this.tableName] ?? []) {
                    const key = item[KEY_ATTRIBUTE]?.S
                    const expiresAt = Number(item[EXPIRES_AT_ATTRIBUTE]?.N)
                    if (!key || !Number.isFinite(expiresAt)) {
                        if (key) {
                            addIndexes(failed, [key], indexesByKey)
                        }
                        continue
                    }
                    if (expiresAt > nowSeconds) {
                        addIndexes(known, [key], indexesByKey)
                    }
                }

                pending = (response.UnprocessedKeys?.[this.tableName]?.Keys ?? []).flatMap((key) => {
                    const value = key[KEY_ATTRIBUTE]?.S
                    return value ? [value] : []
                })
                if (pending.length === 0) {
                    return
                }
                if (attempt === UNPROCESSED_MAX_ATTEMPTS) {
                    addIndexes(failed, pending, indexesByKey)
                    return
                }
                await this.backoffBeforeRetry(attempt)
            }
        })

        return { known, failed }
    }

    public async record(keys: string[], nowMs: number, ttlSeconds: number): Promise<{ failed: Set<number> }> {
        const failed = new Set<number>()
        const indexesByKey = indexKeys(keys)
        const expiresAt = Math.floor(nowMs / 1000) + ttlSeconds
        const requests = [...indexesByKey.keys()].map(
            (key): WriteRequest => ({
                PutRequest: {
                    Item: {
                        [KEY_ATTRIBUTE]: { S: key },
                        [EXPIRES_AT_ATTRIBUTE]: { N: String(expiresAt) },
                    },
                },
            })
        )
        const startedAt = process.hrtime.bigint()

        await this.runChunks(chunk(requests, BATCH_WRITE_SIZE), async (batch) => {
            let pending = batch
            for (let attempt = 1; attempt <= UNPROCESSED_MAX_ATTEMPTS; attempt++) {
                if (this.batchBudgetSpent(startedAt)) {
                    addIndexes(failed, keysFromWriteRequests(pending), indexesByKey)
                    return
                }

                let response: BatchWriteItemCommandOutput
                try {
                    response = await this.sendBatchWrite(
                        new BatchWriteItemCommand({ RequestItems: { [this.tableName]: pending } })
                    )
                } catch {
                    addIndexes(failed, keysFromWriteRequests(pending), indexesByKey)
                    return
                }

                pending = response.UnprocessedItems?.[this.tableName] ?? []
                if (pending.length === 0) {
                    return
                }
                if (attempt === UNPROCESSED_MAX_ATTEMPTS) {
                    addIndexes(failed, keysFromWriteRequests(pending), indexesByKey)
                    return
                }
                await this.backoffBeforeRetry(attempt)
            }
        })

        return { failed }
    }

    private async runChunks<T>(chunks: T[][], run: (batch: T[]) => Promise<void>): Promise<void> {
        let nextChunk = 0
        const worker = async (): Promise<void> => {
            while (nextChunk < chunks.length) {
                const batch = chunks[nextChunk++]
                await run(batch)
            }
        }
        const workerCount = Math.min(chunks.length, MAX_CONCURRENT_BATCH_REQUESTS)
        await Promise.all(Array.from({ length: workerCount }, worker))
    }

    private batchBudgetSpent(startedAt: bigint): boolean {
        return Number(process.hrtime.bigint() - startedAt) / 1e6 > this.batchBudgetMs
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
