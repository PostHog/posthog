import { BatchGetItemCommand, BatchWriteItemCommand } from '@aws-sdk/client-dynamodb'

import { DynamoDBCrawlHistory, DynamoDBCrawlHistoryClient } from './dynamodb-crawl-history'

const TABLE = 'ai-research-image-fetch-crawl-history'
const NOW_MS = 1_700_000_000_000
const NOW_SECONDS = Math.floor(NOW_MS / 1000)
const KEYS = Array.from({ length: 205 }, (_value, index) => `k${index}`)

function dynamoClient(send: jest.Mock): DynamoDBCrawlHistoryClient {
    return { send }
}

function requestedReadKeys(command: BatchGetItemCommand): string[] {
    return (command.input.RequestItems?.[TABLE].Keys ?? []).flatMap((key) => (key.key?.S ? [key.key.S] : []))
}

function requestedWriteKeys(command: BatchWriteItemCommand): string[] {
    return (command.input.RequestItems?.[TABLE] ?? []).flatMap((request) =>
        request.PutRequest?.Item?.key?.S ? [request.PutRequest.Item.key.S] : []
    )
}

describe('DynamoDBCrawlHistory', () => {
    const build = (send: jest.Mock): DynamoDBCrawlHistory =>
        new DynamoDBCrawlHistory(dynamoClient(send), TABLE, 1_000, 60_000)

    it('validates batch write and consistent read access', async () => {
        const send = jest.fn((command: BatchGetItemCommand | BatchWriteItemCommand) =>
            command instanceof BatchWriteItemCommand
                ? Promise.resolve({})
                : Promise.resolve({ Responses: { [TABLE]: [{ key: { S: 'imgfetch:access-probe' } }] } })
        )

        await build(send).validateAccess(NOW_MS)

        expect(send).toHaveBeenCalledTimes(2)
        expect(send.mock.calls[0][0]).toBeInstanceOf(BatchWriteItemCommand)
        const readCommand = send.mock.calls[1][0] as BatchGetItemCommand
        expect(readCommand).toBeInstanceOf(BatchGetItemCommand)
        expect(readCommand.input.RequestItems?.[TABLE].ConsistentRead).toBe(true)
    })

    it.each([
        {
            name: 'an unprocessed write',
            responses: [
                {
                    UnprocessedItems: {
                        [TABLE]: [{ PutRequest: { Item: { key: { S: 'imgfetch:access-probe' } } } }],
                    },
                },
            ],
        },
        {
            name: 'an unprocessed read',
            responses: [{}, { UnprocessedKeys: { [TABLE]: { Keys: [{ key: { S: 'imgfetch:access-probe' } }] } } }],
        },
        {
            name: 'a missing probe record',
            responses: [{}, { Responses: { [TABLE]: [] } }],
        },
    ])('rejects $name during access validation', async ({ responses }) => {
        const send = jest.fn()
        responses.forEach((response) => send.mockResolvedValueOnce(response))

        await expect(build(send).validateAccess(NOW_MS)).rejects.toThrow('access probe')
    })

    it('reads the whole candidate set with DynamoDB batch operations', async () => {
        const active = new Set(['k0', 'k99', 'k100', 'k204'])
        const send = jest.fn((command: BatchGetItemCommand) => {
            const items = requestedReadKeys(command)
                .filter((key) => active.has(key) || key === 'k1')
                .map((key) => ({
                    key: { S: key },
                    expires_at: { N: String(key === 'k1' ? NOW_SECONDS : NOW_SECONDS + 1) },
                }))
            return Promise.resolve({ Responses: { [TABLE]: items } })
        })

        const result = await build(send).read(KEYS, NOW_MS)

        expect([...result.known].sort((left, right) => left - right)).toEqual([0, 99, 100, 204])
        expect(result.failed.size).toBe(0)
        const commands = send.mock.calls.map(([command]) => command as BatchGetItemCommand)
        expect(commands).toHaveLength(3)
        expect(commands.every((command) => requestedReadKeys(command).length <= 100)).toBe(true)
    })

    it('runs read batches with bounded concurrency', async () => {
        const manyKeys = Array.from({ length: 1_601 }, (_value, index) => `key-${index}`)
        let holdInitialRequests = true
        const releaseInitialRequests: Array<() => void> = []
        const send = jest.fn(() => {
            if (!holdInitialRequests) {
                return Promise.resolve({ Responses: { [TABLE]: [] } })
            }
            return new Promise((resolve) => releaseInitialRequests.push(() => resolve({ Responses: { [TABLE]: [] } })))
        })

        const readPromise = build(send).read(manyKeys, NOW_MS)
        await Promise.resolve()

        expect(send.mock.calls.length).toBeGreaterThan(1)
        expect(send.mock.calls.length).toBeLessThan(Math.ceil(manyKeys.length / 100))

        holdInitialRequests = false
        releaseInitialRequests.forEach((release) => release())
        await readPromise

        expect(send).toHaveBeenCalledTimes(Math.ceil(manyKeys.length / 100))
    })

    it('treats expired rows as absent before DynamoDB deletes them', async () => {
        const send = jest.fn(() =>
            Promise.resolve({
                Responses: {
                    [TABLE]: [{ key: { S: 'expired' }, expires_at: { N: String(NOW_SECONDS - 1) } }],
                },
            })
        )

        const result = await build(send).read(['expired'], NOW_MS)

        expect(result.known.size).toBe(0)
        expect(result.failed.size).toBe(0)
    })

    it('reports only the keys whose batched read failed', async () => {
        const send = jest.fn((command: BatchGetItemCommand) => {
            const requested = requestedReadKeys(command)
            return requested.includes('k100')
                ? Promise.reject(new Error('dynamodb unavailable'))
                : Promise.resolve({ Responses: { [TABLE]: [] } })
        })

        const result = await build(send).read(KEYS, NOW_MS)

        expect(result.failed.size).toBe(100)
        expect(result.failed.has(100)).toBe(true)
        expect(result.failed.has(99)).toBe(false)
    })

    it('retries unprocessed read keys as a batch', async () => {
        const send = jest
            .fn()
            .mockResolvedValueOnce({
                UnprocessedKeys: { [TABLE]: { Keys: [{ key: { S: 'retry' } }] } },
            })
            .mockResolvedValueOnce({
                Responses: {
                    [TABLE]: [{ key: { S: 'retry' }, expires_at: { N: String(NOW_SECONDS + 1) } }],
                },
            })

        const result = await build(send).read(['retry'], NOW_MS)

        expect(result.known).toEqual(new Set([0]))
        expect(result.failed.size).toBe(0)
        expect(send).toHaveBeenCalledTimes(2)
    })

    it.each([
        {
            name: 'read',
            response: { UnprocessedKeys: { [TABLE]: { Keys: [{ key: { S: 'retry' } }] } } },
            run: (crawlHistory: DynamoDBCrawlHistory) => crawlHistory.read(['retry'], NOW_MS),
        },
        {
            name: 'write',
            response: {
                UnprocessedItems: {
                    [TABLE]: [{ PutRequest: { Item: { key: { S: 'retry' } } } }],
                },
            },
            run: (crawlHistory: DynamoDBCrawlHistory) => crawlHistory.record(['retry'], NOW_MS, 60),
        },
    ])('reports a failed key when unprocessed $name retries are exhausted', async ({ response, run }) => {
        jest.useFakeTimers()
        try {
            const send = jest.fn().mockResolvedValue(response)
            const resultPromise = run(build(send))

            await jest.runAllTimersAsync()
            const result = await resultPromise

            expect(result.failed).toEqual(new Set([0]))
            expect(send).toHaveBeenCalledTimes(5)
        } finally {
            jest.useRealTimers()
        }
    })

    it('flushes every new row with bounded batch writes and one expiry', async () => {
        const send = jest.fn((_command: BatchWriteItemCommand) => Promise.resolve({}))

        const result = await build(send).record(KEYS, NOW_MS, 30 * 24 * 60 * 60)

        expect(result.failed.size).toBe(0)
        const commands = send.mock.calls.map(([command]) => command as BatchWriteItemCommand)
        expect(commands).toHaveLength(9)
        expect(commands.every((command) => requestedWriteKeys(command).length <= 25)).toBe(true)
        expect(commands.flatMap(requestedWriteKeys).sort()).toEqual([...KEYS].sort())
        for (const command of commands) {
            for (const request of command.input.RequestItems?.[TABLE] ?? []) {
                expect(request.PutRequest?.Item?.expires_at?.N).toBe(String(NOW_SECONDS + 30 * 24 * 60 * 60))
            }
        }
    })
})
