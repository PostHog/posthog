import { config } from '../config'
import { buildPlayerConfig } from '../player'
import { RasterizeRecordingInput } from '../types'

function baseInput(overrides: Partial<RasterizeRecordingInput> = {}): RasterizeRecordingInput {
    return {
        session_id: 'test-session-123',
        team_id: 1,
        s3_bucket: 'test-bucket',
        s3_key_prefix: 'exports/mp4/team-1/task-1',
        ...overrides,
    }
}

describe('buildPlayerConfig', () => {
    it('includes session_id and team_id', () => {
        const result = buildPlayerConfig(baseInput({ session_id: 'abc-123', team_id: 42 }), 4, config)
        expect(result.sessionId).toBe('abc-123')
        expect(result.teamId).toBe(42)
    })

    it('sets skipInactivity and playbackSpeed', () => {
        const result = buildPlayerConfig(baseInput(), 8, config)
        expect(result.skipInactivity).toBe(true)
        expect(result.playbackSpeed).toBe(8)
    })

    it('passes showMetadataFooter flag', () => {
        const result = buildPlayerConfig(baseInput({ show_metadata_footer: true }), 4, config)
        expect(result.showMetadataFooter).toBe(true)
    })

    it('passes startTimestamp and endTimestamp', () => {
        const result = buildPlayerConfig(
            baseInput({ start_timestamp: 1700000000000, end_timestamp: 1700000060000 }),
            4,
            config
        )
        expect(result.startTimestamp).toBe(1700000000000)
        expect(result.endTimestamp).toBe(1700000060000)
    })

    it('omits startTimestamp and endTimestamp when not provided', () => {
        const result = buildPlayerConfig(baseInput(), 4, config)
        expect(result.startTimestamp).toBeUndefined()
        expect(result.endTimestamp).toBeUndefined()
    })

    it('passes skipInactivity=false when explicitly disabled', () => {
        const result = buildPlayerConfig(baseInput({ skip_inactivity: false }), 4, config)
        expect(result.skipInactivity).toBe(false)
    })

    it('passes mouseTail=false when explicitly disabled', () => {
        const result = buildPlayerConfig(baseInput({ mouse_tail: false }), 4, config)
        expect(result.mouseTail).toBe(false)
    })

    it('passes viewport events', () => {
        const events = [{ timestamp: 1000, width: 1920, height: 1080 }]
        const result = buildPlayerConfig(baseInput({ viewport_events: events }), 4, config)
        expect(result.viewportEvents).toEqual(events)
    })

    it('includes recording API config from cfg', () => {
        const result = buildPlayerConfig(baseInput(), 4, config)
        expect(result.recordingApiBaseUrl).toBe(config.recordingApiBaseUrl)
        expect(result.recordingApiSecret).toBe(config.recordingApiSecret)
    })
})
