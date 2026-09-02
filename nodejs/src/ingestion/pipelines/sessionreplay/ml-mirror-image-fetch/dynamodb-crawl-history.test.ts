import { BatchGetItemCommand, BatchWriteItemCommand } from '@aws-sdk/client-dynamodb'

import { parseJSON } from '~/common/utils/json-parse'

import { ConfigurationCacheItem, CrawlHistoryItem, UrlCrawlHistoryItem } from './crawl-history'
import { DynamoDBCrawlHistory, DynamoDBCrawlHistoryClient } from './dynamodb-crawl-history'

const TABLE = 'crawl-history'
const NOW_MS = 1_700_000_000_123

function urlItem(key: string, overrides: Partial<UrlCrawlHistoryItem> = {}): UrlCrawlHistoryItem {
    return {
        kind: 'url',
        key,
        nextFetchAtMs: NOW_MS + 30 * 24 * 60 * 60 * 1000,
        storageExpiresAtMs: NOW_MS + 30 * 24 * 60 * 60 * 1000,
        outcome: 'ok',
        ...overrides,
    }
}

function stored(item: CrawlHistoryItem): Record<string, { S?: string; N?: string }> {
    return {
        key: { S: item.key },
        expires_at: { N: String(Math.ceil(item.storageExpiresAtMs / 1000)) },
        value: { S: JSON.stringify(item) },
    }
}

function build(send: jest.Mock, batchBudgetMs = 10_000): DynamoDBCrawlHistory {
    return new DynamoDBCrawlHistory({ send } as unknown as DynamoDBCrawlHistoryClient, TABLE, 1_000, batchBudgetMs)
}

function requestedReadKeys(command: BatchGetItemCommand): string[] {
    return command.input.RequestItems?.[TABLE]?.Keys?.flatMap((key) => (key.key?.S ? [key.key.S] : [])) ?? []
}

function requestedWrites(
    command: BatchWriteItemCommand
): NonNullable<BatchWriteItemCommand['input']['RequestItems']>[string] {
    return command.input.RequestItems?.[TABLE] ?? []
}

describe('DynamoDBCrawlHistory', () => {
    it('reads each distinct key in batches of at most 100', async () => {
        const send = jest.fn((command: BatchGetItemCommand) => {
            const items = requestedReadKeys(command).map((key) => stored(urlItem(key)))
            return Promise.resolve({ Responses: { [TABLE]: items } })
        })
        const keys = [...Array.from({ length: 205 }, (_, index) => `k${index}`), 'k0']

        const result = await build(send).read(keys)

        expect(result).toHaveProperty('size', 205)
        expect(send).toHaveBeenCalledTimes(3)
        expect(send.mock.calls.map(([command]) => requestedReadKeys(command))).toEqual(
            expect.arrayContaining([expect.any(Array), expect.any(Array), expect.any(Array)])
        )
        expect(send.mock.calls.every(([command]) => requestedReadKeys(command).length <= 100)).toBe(true)
    })

    it('reads a legacy expiry-only URL item', async () => {
        const send = jest.fn(() =>
            Promise.resolve({
                Responses: {
                    [TABLE]: [{ key: { S: 'legacy' }, expires_at: { N: String(Math.ceil(NOW_MS / 1000)) } }],
                },
            })
        )

        await expect(build(send).read(['legacy'])).resolves.toEqual(
            new Map([
                [
                    'legacy',
                    {
                        kind: 'url',
                        key: 'legacy',
                        nextFetchAtMs: Math.ceil(NOW_MS / 1000) * 1000,
                        storageExpiresAtMs: Math.ceil(NOW_MS / 1000) * 1000,
                        outcome: 'legacy',
                    },
                ],
            ])
        )
    })

    it('retries only unprocessed read keys', async () => {
        const send = jest
            .fn()
            .mockResolvedValueOnce({
                Responses: { [TABLE]: [stored(urlItem('done'))] },
                UnprocessedKeys: { [TABLE]: { Keys: [{ key: { S: 'retry' } }] } },
            })
            .mockResolvedValueOnce({ Responses: { [TABLE]: [stored(urlItem('retry'))] } })

        const result = await build(send).read(['done', 'retry'])

        expect([...result.keys()].sort()).toEqual(['done', 'retry'])
        expect(requestedReadKeys(send.mock.calls[1][0])).toEqual(['retry'])
    })

    it('throws when a read request fails', async () => {
        const send = jest.fn(() => Promise.reject(new Error('DynamoDB unavailable')))

        await expect(build(send).read(['a'])).rejects.toThrow('DynamoDB unavailable')
    })

    it('throws when DynamoDB returns a malformed item', async () => {
        const send = jest.fn(() =>
            Promise.resolve({ Responses: { [TABLE]: [{ key: { S: 'a' }, expires_at: { N: 'invalid' } }] } })
        )

        await expect(build(send).read(['a'])).rejects.toThrow('malformed crawl-history item')
    })

    it('throws when a stored value has an invalid nested shape', async () => {
        const item = stored(urlItem('a'))
        item.value = { S: JSON.stringify({ ...urlItem('a'), cache: { requestTimeMs: 'invalid' } }) }
        const send = jest.fn(() => Promise.resolve({ Responses: { [TABLE]: [item] } }))

        await expect(build(send).read(['a'])).rejects.toThrow('invalid crawl-history value')
    })

    it('folds repeated updates and writes batches of at most 25', async () => {
        const send: jest.Mock<Promise<unknown>, [BatchWriteItemCommand]> = jest.fn((_command) => Promise.resolve({}))
        const first = urlItem('same', { outcome: 'first' })
        const last = urlItem('same', { outcome: 'last', storageExpiresAtMs: NOW_MS + 1 })
        const items = [first, ...Array.from({ length: 55 }, (_, index) => urlItem(`k${index}`)), last]

        await build(send).write(items)

        expect(send).toHaveBeenCalledTimes(3)
        const requests = send.mock.calls.flatMap(([command]) => requestedWrites(command))
        expect(send.mock.calls.every(([command]) => requestedWrites(command).length <= 25)).toBe(true)
        expect(requests).toHaveLength(56)
        const same = requests.find((request) => request.PutRequest?.Item?.key?.S === 'same')
        expect(parseJSON(same?.PutRequest?.Item?.value?.S ?? '{}')).toMatchObject({ outcome: 'last' })
        expect(same?.PutRequest?.Item?.expires_at?.N).toBe(String(Math.ceil((NOW_MS + 1) / 1000)))
    })

    it('retries only unprocessed writes', async () => {
        const send = jest
            .fn()
            .mockImplementationOnce((command: BatchWriteItemCommand) =>
                Promise.resolve({ UnprocessedItems: { [TABLE]: [requestedWrites(command)[1]] } })
            )
            .mockResolvedValueOnce({})

        await build(send).write([urlItem('done'), urlItem('retry')])

        expect(requestedWrites(send.mock.calls[1][0])).toHaveLength(1)
        expect(requestedWrites(send.mock.calls[1][0])[0].PutRequest?.Item?.key?.S).toBe('retry')
    })

    it('splits and reassembles a 500 KiB configuration body', async () => {
        const dynamoItems = new Map<string, Record<string, { S?: string; N?: string }>>()
        const send = jest.fn((command: BatchWriteItemCommand | BatchGetItemCommand) => {
            if (command instanceof BatchWriteItemCommand) {
                for (const request of requestedWrites(command)) {
                    const item = request.PutRequest?.Item as Record<string, { S?: string; N?: string }>
                    dynamoItems.set(item.key.S ?? '', item)
                }
                return Promise.resolve({})
            }
            return Promise.resolve({
                Responses: {
                    [TABLE]: requestedReadKeys(command).flatMap((key) => {
                        const item = dynamoItems.get(key)
                        return item ? [item] : []
                    }),
                },
            })
        })
        const body = 'abc😀'.repeat(73_000)
        const item: ConfigurationCacheItem = {
            kind: 'robots',
            key: 'imgfetch:config:robots:https://example.com',
            origin: 'https://example.com',
            status: 'available',
            body,
            fetchedAtMs: NOW_MS,
            refreshAtMs: NOW_MS + 1,
            freshUntilMs: NOW_MS + 2,
            retryAtMs: NOW_MS,
            storageExpiresAtMs: NOW_MS + 3,
        }
        const store = build(send)

        await store.write([item])
        const result = await store.read([item.key])

        expect(result.get(item.key)).toEqual(item)
        expect(dynamoItems.size).toBe(4)
        const writeCalls = send.mock.calls.filter(([command]) => command instanceof BatchWriteItemCommand)
        expect(requestedWrites(writeCalls[0][0] as BatchWriteItemCommand)).toHaveLength(3)
        expect(
            requestedWrites(writeCalls[0][0] as BatchWriteItemCommand).every((request) =>
                request.PutRequest?.Item?.key?.S?.startsWith(`${item.key}:body:`)
            )
        ).toBe(true)
        expect(requestedWrites(writeCalls[1][0] as BatchWriteItemCommand)[0].PutRequest?.Item?.key?.S).toBe(item.key)
        expect(
            [...dynamoItems.values()].every((storedItem) => Buffer.byteLength(JSON.stringify(storedItem)) < 400 * 1024)
        ).toBe(true)
    })

    it('treats an incomplete configuration body generation as a cache miss', async () => {
        const sha256 = 'a'.repeat(64)
        const item: ConfigurationCacheItem = {
            kind: 'robots',
            key: 'imgfetch:config:robots:https://example.com',
            origin: 'https://example.com',
            status: 'available',
            fetchedAtMs: NOW_MS,
            refreshAtMs: NOW_MS + 1,
            freshUntilMs: NOW_MS + 2,
            retryAtMs: NOW_MS,
            storageExpiresAtMs: NOW_MS + 3,
        }
        const manifest = stored(item)
        manifest.value = { S: JSON.stringify({ ...item, _bodyChunks: { count: 2, sha256 } }) }
        const send = jest
            .fn()
            .mockResolvedValueOnce({ Responses: { [TABLE]: [manifest] } })
            .mockResolvedValueOnce({ Responses: { [TABLE]: [] } })

        await expect(build(send).read([item.key])).resolves.toEqual(new Map())
    })

    it('does not publish a manifest when its body chunks cannot be written', async () => {
        jest.useFakeTimers()
        jest.spyOn(Math, 'random').mockReturnValue(0)
        const sentKeys: string[] = []
        const send = jest.fn((command: BatchWriteItemCommand) => {
            const writes = requestedWrites(command)
            sentKeys.push(...writes.flatMap((request) => request.PutRequest?.Item?.key?.S ?? []))
            return Promise.resolve({ UnprocessedItems: { [TABLE]: writes } })
        })
        const key = 'imgfetch:config:robots:https://example.com'
        const item: ConfigurationCacheItem = {
            kind: 'robots',
            key,
            origin: 'https://example.com',
            status: 'available',
            body: 'abc😀'.repeat(73_000),
            fetchedAtMs: NOW_MS,
            refreshAtMs: NOW_MS + 1,
            freshUntilMs: NOW_MS + 2,
            retryAtMs: NOW_MS,
            storageExpiresAtMs: NOW_MS + 3,
        }

        const write = build(send).write([item])
        const refused = expect(write).rejects.toThrow('crawl-history writes unprocessed')
        await jest.runAllTimersAsync()

        await refused
        expect(sentKeys.length).toBeGreaterThan(0)
        expect(sentKeys.every((sentKey) => sentKey.startsWith(`${key}:body:`))).toBe(true)
        jest.useRealTimers()
    })

    it('throws after unprocessed write retries are exhausted', async () => {
        jest.useFakeTimers()
        jest.spyOn(Math, 'random').mockReturnValue(0)
        const send = jest.fn((command: BatchWriteItemCommand) =>
            Promise.resolve({ UnprocessedItems: { [TABLE]: requestedWrites(command) } })
        )

        const write = build(send).write([urlItem('retry')])
        const refused = expect(write).rejects.toThrow('crawl-history writes unprocessed: retry')
        await jest.runAllTimersAsync()

        await refused
        expect(send).toHaveBeenCalledTimes(5)
        jest.useRealTimers()
    })

    it('validates write and consistent read access', async () => {
        const send = jest
            .fn()
            .mockResolvedValueOnce({})
            .mockResolvedValueOnce({ Responses: { [TABLE]: [{ key: { S: 'imgfetch:access-probe' } }] } })

        await build(send).validateAccess(NOW_MS)

        expect(send.mock.calls[0][0]).toBeInstanceOf(BatchWriteItemCommand)
        expect(send.mock.calls[1][0]).toBeInstanceOf(BatchGetItemCommand)
        expect(send.mock.calls[1][0].input.RequestItems?.[TABLE]?.ConsistentRead).toBe(true)
    })
})
