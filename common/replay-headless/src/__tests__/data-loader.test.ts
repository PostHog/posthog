import { loadAllSources } from '../data-loader'
import type { PlayerConfig } from '../types'

const makeConfig = (overrides?: Partial<PlayerConfig>): PlayerConfig => ({
    blocks: [
        { key: 'session_recordings/30d/1000-abc123', start: 0, end: 5000 },
        { key: 'session_recordings/30d/2000-def456', start: 100, end: 6000 },
    ],
    recordingApiBaseUrl: 'https://recording.example.com',
    recordingApiSecret: 'test-secret',
    teamId: 1,
    sessionId: 'sess-123',
    playbackSpeed: 4,
    ...overrides,
})

const mockResponse = (
    body: string,
    status = 200,
    statusText = 'OK'
): { ok: boolean; status: number; statusText: string; text: () => Promise<string> } => ({
    ok: status >= 200 && status < 300,
    status,
    statusText,
    text: async () => body,
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

    it('fetches all blocks via the recording-api and returns sources with parsed snapshots', async () => {
        const fetchMock = (globalThis.fetch = jest.fn(async (input: RequestInfo | URL) => {
            const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url
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

        expect(fetchMock).toHaveBeenCalledTimes(2)

        // Verify recording-api URL format and auth header
        const firstCall = fetchMock.mock.calls[0]
        const firstUrl = typeof firstCall[0] === 'string' ? firstCall[0] : ''
        expect(firstUrl).toContain('/api/projects/1/recordings/sess-123/block?')
        expect(firstUrl).toContain('start=0')
        expect(firstUrl).toContain('end=5000')
        expect(firstUrl).toContain('decompress=true')
        expect(firstCall[1]?.headers?.['X-Internal-Api-Secret']).toBe('test-secret')

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

    it('throws on HTTP error with response body', async () => {
        globalThis.fetch = jest.fn().mockResolvedValue(mockResponse('forbidden', 403, 'Forbidden'))

        const config = makeConfig({
            blocks: [{ key: 'session_recordings/30d/bad-block', start: 0, end: 100 }],
        })

        await expect(loadAllSources(config)).rejects.toThrow('Failed to fetch block: 403 Forbidden - forbidden')
    })
})
