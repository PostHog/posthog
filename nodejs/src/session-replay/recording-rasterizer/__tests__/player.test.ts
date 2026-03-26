import { buildPlayerConfig, fetchBlockList } from '../capture/player'
import { RasterizationError } from '../errors'
import { RasterizeRecordingInput } from '../types'

const mockInternalFetch = jest.fn()
jest.mock('../../../utils/request', () => ({
    internalFetch: (...args: any[]) => mockInternalFetch(...args),
}))

function baseInput(overrides: Partial<RasterizeRecordingInput> = {}): RasterizeRecordingInput {
    return {
        session_id: 'test-session-123',
        team_id: 1,
        s3_bucket: 'test-bucket',
        s3_key_prefix: 'exports/mp4/team-1/task-1',
        ...overrides,
    }
}

const testCfg = {
    recordingApiBaseUrl: 'http://localhost:6738',
    recordingApiSecret: 'test-secret',
} as any

describe('fetchBlockList', () => {
    afterEach(() => {
        jest.restoreAllMocks()
        mockInternalFetch.mockReset()
    })

    it('returns parsed blocks on success', async () => {
        const blocks = [
            { key: 'recordings/block-0', start_byte: 0, end_byte: 1000 },
            { key: 'recordings/block-1', start_byte: 0, end_byte: 2000 },
        ]

        mockInternalFetch.mockResolvedValue({
            status: 200,
            json: jest.fn().mockResolvedValue({ blocks }),
        })

        const result = await fetchBlockList(baseInput(), testCfg)
        expect(result).toEqual(blocks)
        expect(mockInternalFetch).toHaveBeenCalledWith(
            'http://localhost:6738/api/projects/1/recordings/test-session-123/blocks',
            { headers: { 'X-Internal-Api-Secret': 'test-secret' } }
        )
    })

    it('throws RasterizationError on non-ok response', async () => {
        mockInternalFetch.mockResolvedValue({
            status: 404,
            text: jest.fn().mockResolvedValue('session not found'),
        })

        await expect(fetchBlockList(baseInput(), testCfg)).rejects.toThrow(RasterizationError)
        await expect(fetchBlockList(baseInput(), testCfg)).rejects.toThrow('Failed to fetch block listing: 404')
    })

    it.each([
        [500, true],
        [403, false],
    ])('marks %i response as retryable=%s', async (status, expectedRetryable) => {
        mockInternalFetch.mockResolvedValue({
            status,
            text: jest.fn().mockResolvedValue('error body'),
        })

        await expect(fetchBlockList(baseInput(), testCfg)).rejects.toMatchObject({
            retryable: expectedRetryable,
            code: 'BLOCK_LISTING_FAILED',
        })
    })

    it('throws on invalid blocks response', async () => {
        mockInternalFetch.mockResolvedValue({
            status: 200,
            json: jest.fn().mockResolvedValue({ blocks: 'not-an-array' }),
        })

        await expect(fetchBlockList(baseInput(), testCfg)).rejects.toThrow('Invalid block listing response')
    })
})

describe('buildPlayerConfig', () => {
    it('includes session_id and team_id', () => {
        const result = buildPlayerConfig(baseInput({ session_id: 'abc-123', team_id: 42 }), 4, 5)
        expect(result.sessionId).toBe('abc-123')
        expect(result.teamId).toBe(42)
    })

    it('sets skipInactivity and playbackSpeed', () => {
        const result = buildPlayerConfig(baseInput(), 8, 5)
        expect(result.skipInactivity).toBe(true)
        expect(result.playbackSpeed).toBe(8)
    })

    it('passes showMetadataFooter flag', () => {
        const result = buildPlayerConfig(baseInput({ show_metadata_footer: true }), 4, 5)
        expect(result.showMetadataFooter).toBe(true)
    })

    it('passes startTimestamp and endTimestamp', () => {
        const result = buildPlayerConfig(
            baseInput({ start_timestamp: 1700000000000, end_timestamp: 1700000060000 }),
            4,
            5
        )
        expect(result.startTimestamp).toBe(1700000000000)
        expect(result.endTimestamp).toBe(1700000060000)
    })

    it('omits startTimestamp and endTimestamp when not provided', () => {
        const result = buildPlayerConfig(baseInput(), 4, 5)
        expect(result.startTimestamp).toBeUndefined()
        expect(result.endTimestamp).toBeUndefined()
    })

    it('passes skipInactivity=false when explicitly disabled', () => {
        const result = buildPlayerConfig(baseInput({ skip_inactivity: false }), 4, 5)
        expect(result.skipInactivity).toBe(false)
    })

    it('passes mouseTail=false when explicitly disabled', () => {
        const result = buildPlayerConfig(baseInput({ mouse_tail: false }), 4, 5)
        expect(result.mouseTail).toBe(false)
    })

    it('passes viewport events', () => {
        const events = [{ timestamp: 1000, width: 1920, height: 1080 }]
        const result = buildPlayerConfig(baseInput({ viewport_events: events }), 4, 5)
        expect(result.viewportEvents).toEqual(events)
    })

    it('does not include recording API secret in player config', () => {
        const result = buildPlayerConfig(baseInput(), 4, 5)
        expect(result).not.toHaveProperty('recordingApiSecret')
    })
})
