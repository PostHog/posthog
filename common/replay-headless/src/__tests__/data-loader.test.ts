import { loadAllSources } from '../data-loader'
import type { PlayerConfig, RecordingBlock } from '../types'

const makeConfig = (overrides?: Partial<PlayerConfig>): PlayerConfig => ({
    recordingApiBaseUrl: 'https://recording.example.com',
    recordingApiSecret: 'test-secret',
    teamId: 1,
    sessionId: 'sess-123',
    playbackSpeed: 4,
    ...overrides,
})

const blocks: RecordingBlock[] = [
    {
        key: 'session_recordings/30d/1000-abc123',
        start_byte: 0,
        end_byte: 5000,
        start_timestamp: '2024-01-01T00:00:00Z',
        end_timestamp: '2024-01-01T00:01:00Z',
    },
    {
        key: 'session_recordings/30d/2000-def456',
        start_byte: 100,
        end_byte: 6000,
        start_timestamp: '2024-01-01T00:01:00Z',
        end_timestamp: '2024-01-01T00:02:00Z',
    },
]

const mockResponse = (
    body: string | object,
    status = 200,
    statusText = 'OK'
): { ok: boolean; status: number; statusText: string; text: () => Promise<string>; json: () => Promise<unknown> } => ({
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
                data: [{ type: 4, timestamp: ts, data: { href: 'https://example.com', width: 1920, height: 1080 } }],
            })
        )
        .join('\n')

describe('data-loader', () => {
    afterEach(() => {
        jest.restoreAllMocks()
        // @ts-expect-error cleaning up mock
        delete globalThis.fetch
    })

    it('fetches block listing then fetches each block', async () => {
        const fetchMock = (globalThis.fetch = jest.fn(async (input: RequestInfo | URL) => {
            const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
            if (url.endsWith('/blocks')) {
                return mockResponse({ blocks })
            }
            if (url.includes('key=session_recordings%2F30d%2F1000-abc123')) {
                return mockResponse(jsonlBlock('win-1', [1000, 2000]))
            }
            if (url.includes('key=session_recordings%2F30d%2F2000-def456')) {
                return mockResponse(jsonlBlock('win-1', [3000, 4000]))
            }
            return mockResponse('not found', 404, 'Not Found')
        }) as jest.Mock)

        const config = makeConfig()
        const { sources, snapshotsBySource } = await loadAllSources(config)

        // 1 listing call + 2 block fetches
        expect(fetchMock).toHaveBeenCalledTimes(3)

        // Verify listing URL and auth header
        const listingCall = fetchMock.mock.calls[0]
        const listingUrl = typeof listingCall[0] === 'string' ? listingCall[0] : ''
        expect(listingUrl).toBe('https://recording.example.com/api/projects/1/recordings/sess-123/blocks')
        expect(listingCall[1]?.headers?.['X-Internal-Api-Secret']).toBe('test-secret')

        // Verify block fetch URL format
        const blockCall = fetchMock.mock.calls.find((c) => {
            const u = typeof c[0] === 'string' ? c[0] : ''
            return u.includes('/block?')
        })
        const blockUrl = typeof blockCall![0] === 'string' ? blockCall![0] : ''
        expect(blockUrl).toContain('decompress=true')
        expect(blockCall![1]?.headers?.['X-Internal-Api-Secret']).toBe('test-secret')

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

    it('returns empty sources when block listing is empty', async () => {
        globalThis.fetch = jest.fn().mockResolvedValue(mockResponse({ blocks: [] }))

        const { sources, snapshotsBySource } = await loadAllSources(makeConfig())

        expect(sources).toHaveLength(0)
        expect(Object.keys(snapshotsBySource)).toHaveLength(0)
    })

    it('throws on block listing HTTP error', async () => {
        globalThis.fetch = jest.fn().mockResolvedValue(mockResponse('forbidden', 403, 'Forbidden'))

        await expect(loadAllSources(makeConfig())).rejects.toThrow(
            'Failed to fetch block listing: 403 Forbidden - forbidden'
        )
    })

    it('throws on individual block fetch HTTP error', async () => {
        globalThis.fetch = jest.fn(async (input: RequestInfo | URL) => {
            const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
            if (url.endsWith('/blocks')) {
                return mockResponse({ blocks: [blocks[0]] })
            }
            return mockResponse('not found', 404, 'Not Found')
        }) as jest.Mock

        await expect(loadAllSources(makeConfig())).rejects.toThrow('Failed to fetch block: 404 Not Found - not found')
    })
})
