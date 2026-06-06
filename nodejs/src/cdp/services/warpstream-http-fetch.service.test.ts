import { parseJSON } from '../../utils/json-parse'
import { internalFetch } from '../../utils/request'
import { RecordRef, WarpstreamHttpFetchService } from './warpstream-http-fetch.service'

const b64 = (s: string): string => Buffer.from(s).toString('base64')

interface FetchPartition {
    partition: number
    records?: { offset: number; value: string | null }[]
}

const response = (partitions: FetchPartition[]): Awaited<ReturnType<typeof internalFetch>> =>
    ({
        status: 200,
        headers: {},
        json: () => Promise.resolve({ topics: [{ topic: 'results', partitions }] }),
        text: () => Promise.resolve(''),
        dump: () => Promise.resolve(),
    }) as Awaited<ReturnType<typeof internalFetch>>

const requestBody = (mock: jest.Mock, call = 0): any => parseJSON(mock.mock.calls[call][1].body)

describe('WarpstreamHttpFetchService', () => {
    const config = { url: 'http://agent:8080/', username: '', password: '' }

    const fetchRecords = (fetchImpl: jest.Mock, refs: RecordRef[]): Promise<Map<string, Buffer>> =>
        new WarpstreamHttpFetchService(config, fetchImpl as unknown as typeof internalFetch).fetchRecords(
            'results',
            refs
        )

    it('fetches records across partitions in a single batched request', async () => {
        const fetchImpl = jest.fn().mockResolvedValue(
            response([
                {
                    partition: 0,
                    records: [
                        { offset: 5, value: b64('A') },
                        { offset: 6, value: b64('B') },
                    ],
                },
                { partition: 1, records: [{ offset: 10, value: b64('C') }] },
            ])
        )

        const out = await fetchRecords(fetchImpl, [
            { partition: 0, offset: 5 },
            { partition: 0, offset: 6 },
            { partition: 1, offset: 10 },
        ])

        expect(fetchImpl).toHaveBeenCalledTimes(1)
        expect(out.get('0:5')?.toString()).toBe('A')
        expect(out.get('0:6')?.toString()).toBe('B')
        expect(out.get('1:10')?.toString()).toBe('C')

        // Each partition fetched from its lowest wanted offset, batched together.
        const body = requestBody(fetchImpl)
        expect(body.topics[0].partitions).toEqual([
            expect.objectContaining({ partition: 0, fetch_offset: 5 }),
            expect.objectContaining({ partition: 1, fetch_offset: 10 }),
        ])
    })

    it('pages across rounds when a partition spread exceeds one fetch budget', async () => {
        const fetchImpl = jest
            .fn()
            // Round 1: only the contiguous run near offset 5 comes back.
            .mockResolvedValueOnce(
                response([
                    {
                        partition: 0,
                        records: [
                            { offset: 5, value: b64('A') },
                            { offset: 6, value: b64('B') },
                        ],
                    },
                ])
            )
            // Round 2: the far offset, fetched from its own start.
            .mockResolvedValueOnce(response([{ partition: 0, records: [{ offset: 100, value: b64('Z') }] }]))

        const out = await fetchRecords(fetchImpl, [
            { partition: 0, offset: 5 },
            { partition: 0, offset: 100 },
        ])

        expect(fetchImpl).toHaveBeenCalledTimes(2)
        expect(requestBody(fetchImpl, 0).topics[0].partitions[0].fetch_offset).toBe(5)
        expect(requestBody(fetchImpl, 1).topics[0].partitions[0].fetch_offset).toBe(100)
        expect(out.get('0:5')?.toString()).toBe('A')
        expect(out.get('0:100')?.toString()).toBe('Z')
    })

    it('drops a wanted offset that falls in a gap without looping forever', async () => {
        // Offset 6 never appears; the round returns past it (7), so it is
        // abandoned rather than re-requested indefinitely.
        const fetchImpl = jest.fn().mockResolvedValue(
            response([
                {
                    partition: 0,
                    records: [
                        { offset: 5, value: b64('A') },
                        { offset: 7, value: b64('C') },
                    ],
                },
            ])
        )

        const out = await fetchRecords(fetchImpl, [
            { partition: 0, offset: 5 },
            { partition: 0, offset: 6 },
        ])

        expect(fetchImpl).toHaveBeenCalledTimes(1)
        expect(out.get('0:5')?.toString()).toBe('A')
        expect(out.has('0:6')).toBe(false)
    })

    it('skips tombstone (null value) records', async () => {
        const fetchImpl = jest
            .fn()
            .mockResolvedValue(response([{ partition: 0, records: [{ offset: 5, value: null }] }]))

        const out = await fetchRecords(fetchImpl, [{ partition: 0, offset: 5 }])
        expect(out.has('0:5')).toBe(false)
    })

    it('sets basic auth when credentials are provided', async () => {
        const fetchImpl = jest
            .fn()
            .mockResolvedValue(response([{ partition: 0, records: [{ offset: 5, value: b64('A') }] }]))
        const service = new WarpstreamHttpFetchService(
            { url: 'http://agent:8080', username: 'user', password: 'pass' },
            fetchImpl as unknown as typeof internalFetch
        )

        await service.fetchRecords('results', [{ partition: 0, offset: 5 }])

        const headers = fetchImpl.mock.calls[0][1].headers
        expect(headers.authorization).toBe(`Basic ${Buffer.from('user:pass').toString('base64')}`)
    })

    it('returns an empty map (no throw) on a non-ok response', async () => {
        const fetchImpl = jest.fn().mockResolvedValue({
            status: 503,
            headers: {},
            json: () => Promise.resolve({}),
            text: () => Promise.resolve(''),
            dump: () => Promise.resolve(),
        } as Awaited<ReturnType<typeof internalFetch>>)
        const out = await fetchRecords(fetchImpl, [{ partition: 0, offset: 5 }])
        expect(out.size).toBe(0)
    })

    it('returns an empty map (no throw) when the request rejects', async () => {
        const fetchImpl = jest.fn().mockRejectedValue(new Error('connection refused'))
        const out = await fetchRecords(fetchImpl, [{ partition: 0, offset: 5 }])
        expect(out.size).toBe(0)
    })

    it('builds the endpoint URL without a double slash', async () => {
        const fetchImpl = jest.fn().mockResolvedValue(response([{ partition: 0, records: [] }]))
        await fetchRecords(fetchImpl, [{ partition: 0, offset: 5 }])
        expect(fetchImpl.mock.calls[0][0]).toBe('http://agent:8080/v1/kafka/fetch')
    })
})
