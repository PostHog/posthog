import { loadAllSources } from '../data-loader'
import { BLOCK_REQUEST_PREFIX } from '../protocol'
import type { PlayerConfig } from '../types'

const makeConfig = (overrides?: Partial<PlayerConfig>): PlayerConfig => ({
    teamId: 1,
    sessionId: 'sess-123',
    playbackSpeed: 4,
    blockCount: 0,
    ...overrides,
})

const mockResponse = (
    body: string | object,
    status = 200,
    statusText = 'OK'
): {
    ok: boolean
    status: number
    statusText: string
    text: () => Promise<string>
    json: () => Promise<unknown>
} => ({
    ok: status >= 200 && status < 300,
    status,
    statusText,
    text: async () => (typeof body === 'string' ? body : JSON.stringify(body)),
    json: async () => (typeof body === 'string' ? JSON.parse(body) : body),
})

// JSONL lines as recording-api would return them (already decompressed)
const jsonlBlock = (windowId: string, timestamps: number[]): string =>
    timestamps
        .map((ts) =>
            JSON.stringify({
                windowId,
                data: [
                    {
                        type: 4,
                        timestamp: ts,
                        data: { href: 'https://example.com', width: 1920, height: 1080 },
                    },
                ],
            })
        )
        .join('\n')

describe('data-loader', () => {
    afterEach(() => {
        jest.restoreAllMocks()
        // @ts-expect-error cleaning up mock
        delete globalThis.fetch
    })

    it('fetches each block by index based on blockCount from config', async () => {
        const fetchMock = (globalThis.fetch = jest.fn(async (input: RequestInfo | URL) => {
            const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
            if (url === `${BLOCK_REQUEST_PREFIX}0`) {
                return mockResponse(jsonlBlock('win-1', [1000, 2000]))
            }
            if (url === `${BLOCK_REQUEST_PREFIX}1`) {
                return mockResponse(jsonlBlock('win-1', [3000, 4000]))
            }
            return mockResponse('not found', 404, 'Not Found')
        }) as jest.Mock)

        const config = makeConfig({ blockCount: 2 })
        const { sources, snapshotsBySource } = await loadAllSources(config)

        // 2 block fetches (no listing call — count comes from config)
        expect(fetchMock).toHaveBeenCalledTimes(2)

        // Verify block fetch URLs are by index
        const blockUrls = fetchMock.mock.calls.map((c) => (typeof c[0] === 'string' ? c[0] : ''))
        expect(blockUrls).toContain(`${BLOCK_REQUEST_PREFIX}0`)
        expect(blockUrls).toContain(`${BLOCK_REQUEST_PREFIX}1`)

        expect(sources).toHaveLength(2)

        const keys = Object.keys(snapshotsBySource)
        expect(keys).toHaveLength(2)

        for (const key of keys) {
            expect(snapshotsBySource[key].sourceLoaded).toBe(true)
            expect(snapshotsBySource[key].snapshots!.length).toBeGreaterThan(0)
            for (const snap of snapshotsBySource[key].snapshots!) {
                expect(snap).toHaveProperty('timestamp')
                expect(snap).toHaveProperty('windowId')
            }
        }
    })

    it('returns empty sources when blockCount is zero', async () => {
        const { sources, snapshotsBySource } = await loadAllSources(makeConfig({ blockCount: 0 }))

        expect(sources).toHaveLength(0)
        expect(Object.keys(snapshotsBySource)).toHaveLength(0)
    })

    it('throws on individual block fetch HTTP error', async () => {
        globalThis.fetch = jest.fn().mockResolvedValue(mockResponse('not found', 404, 'Not Found')) as jest.Mock

        await expect(loadAllSources(makeConfig({ blockCount: 1 }))).rejects.toThrow(
            'Failed to fetch block: 404 Not Found - not found'
        )
    })
})
