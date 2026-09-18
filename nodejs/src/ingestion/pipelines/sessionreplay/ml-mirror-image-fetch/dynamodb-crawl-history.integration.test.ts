import {
    CreateTableCommand,
    DeleteTableCommand,
    DynamoDBClient,
    GetItemCommand,
    waitUntilTableExists,
} from '@aws-sdk/client-dynamodb'

import { UrlCrawlHistoryItem } from './crawl-history'
import { DynamoDBCrawlHistory } from './dynamodb-crawl-history'

const DYNAMODB_ENDPOINT = 'http://127.0.0.1:18010'
const TABLE_NAME = `ai-research-image-fetch-crawl-history-test-${process.pid}-${Date.now()}`
const NOW_MS = 1_700_000_000_000
const NOW_SECONDS = Math.floor(NOW_MS / 1000)
const TTL_SECONDS = 30 * 24 * 60 * 60
const KEYS = Array.from({ length: 205 }, (_value, index) => `key-${index}`)

describe('DynamoDBCrawlHistory integration', () => {
    const client = new DynamoDBClient({
        endpoint: DYNAMODB_ENDPOINT,
        region: 'us-east-1',
        credentials: { accessKeyId: 'test', secretAccessKey: 'test' },
        maxAttempts: 1,
    })

    beforeAll(async () => {
        await client.send(
            new CreateTableCommand({
                TableName: TABLE_NAME,
                AttributeDefinitions: [{ AttributeName: 'key', AttributeType: 'S' }],
                KeySchema: [{ AttributeName: 'key', KeyType: 'HASH' }],
                BillingMode: 'PAY_PER_REQUEST',
            })
        )
        await waitUntilTableExists({ client, maxWaitTime: 10, minDelay: 1 }, { TableName: TABLE_NAME })
    })

    afterAll(async () => {
        await client.send(new DeleteTableCommand({ TableName: TABLE_NAME }))
        client.destroy()
    })

    it('records and reads a full ingestion batch through DynamoDB', async () => {
        const crawlHistory = new DynamoDBCrawlHistory(client, TABLE_NAME, 5_000, 30_000)

        await crawlHistory.validateAccess(NOW_MS)
        const storageExpiresAtMs = NOW_MS + TTL_SECONDS * 1000
        const items: UrlCrawlHistoryItem[] = KEYS.map((key) => ({
            kind: 'url',
            key,
            nextFetchAtMs: storageExpiresAtMs,
            storageExpiresAtMs,
            outcome: 'ok',
        }))
        await crawlHistory.write(items)
        const readResult = await crawlHistory.read([...KEYS, 'missing'])
        const storedItem = await client.send(
            new GetItemCommand({ TableName: TABLE_NAME, Key: { key: { S: KEYS[0] } }, ConsistentRead: true })
        )

        expect(readResult.size).toBe(KEYS.length)
        expect([...readResult.keys()].sort()).toEqual([...KEYS].sort())
        expect(storedItem.Item?.expires_at?.N).toBe(String(NOW_SECONDS + TTL_SECONDS))
    })
})
