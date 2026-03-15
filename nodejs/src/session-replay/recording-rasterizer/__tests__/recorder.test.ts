import { config } from '../config'
import { buildPlayerHtml, validateInput } from '../recorder'
import { RasterizeRecordingInput } from '../types'

function baseInput(overrides: Partial<RasterizeRecordingInput> = {}): RasterizeRecordingInput {
    return {
        session_id: 'test-session-123',
        team_id: 1,
        capture_timeout: 10,
        playback_speed: 4,
        s3_bucket: 'test-bucket',
        s3_key_prefix: 'exports/mp4/team-1/task-1',
        ...overrides,
    }
}

describe('recorder', () => {
    describe('validateInput', () => {
        it('accepts valid input', () => {
            expect(() => validateInput(baseInput())).not.toThrow()
        })

        it.each([
            { field: 'playback_speed', value: 0, error: 'playback_speed must be positive' },
            { field: 'playback_speed', value: -1, error: 'playback_speed must be positive' },
            { field: 'capture_timeout', value: 0, error: 'capture_timeout must be positive' },
            { field: 'capture_timeout', value: -5, error: 'capture_timeout must be positive' },
            { field: 'recording_fps', value: 0, error: 'recording_fps must be positive' },
            { field: 'recording_fps', value: -10, error: 'recording_fps must be positive' },
        ])('rejects $field=$value', ({ field, value, error }) => {
            expect(() => validateInput(baseInput({ [field]: value }))).toThrow(error)
        })

        it('rejects empty session_id', () => {
            expect(() => validateInput(baseInput({ session_id: '' }))).toThrow('session_id is required')
        })

        it('rejects invalid team_id', () => {
            expect(() => validateInput(baseInput({ team_id: 0 }))).toThrow('team_id must be a positive integer')
            expect(() => validateInput(baseInput({ team_id: -1 }))).toThrow('team_id must be a positive integer')
        })
    })

    describe('buildPlayerHtml', () => {
        const baseHtml = '<html><head><title>Player</title></head><body></body></html>'

        it('injects config script before </head>', () => {
            const result = buildPlayerHtml(baseHtml, baseInput(), 4, config)
            expect(result).toContain('window.__POSTHOG_PLAYER_CONFIG__')
            expect(result).toContain('</head>')
            expect(result.indexOf('__POSTHOG_PLAYER_CONFIG__')).toBeLessThan(result.indexOf('</head>'))
        })

        it('includes session_id and team_id in config', () => {
            const result = buildPlayerHtml(baseHtml, baseInput({ session_id: 'abc-123', team_id: 42 }), 4, config)
            expect(result).toContain('"sessionId":"abc-123"')
            expect(result).toContain('"teamId":42')
        })

        it('sets skipInactivity and playbackSpeed', () => {
            const result = buildPlayerHtml(baseHtml, baseInput(), 8, config)
            expect(result).toContain('"skipInactivity":true')
            expect(result).toContain('"playbackSpeed":8')
        })

        it('passes showMetadataFooter flag', () => {
            const result = buildPlayerHtml(baseHtml, baseInput({ show_metadata_footer: true }), 4, config)
            expect(result).toContain('"showMetadataFooter":true')
        })

        it('passes startTimestamp and endTimestamp to player config', () => {
            const result = buildPlayerHtml(
                baseHtml,
                baseInput({ start_timestamp: 1700000000000, end_timestamp: 1700000060000 }),
                4,
                config
            )
            expect(result).toContain('"startTimestamp":1700000000000')
            expect(result).toContain('"endTimestamp":1700000060000')
        })

        it('omits startTimestamp and endTimestamp when not provided', () => {
            const result = buildPlayerHtml(baseHtml, baseInput(), 4, config)
            const configMatch = result.match(/window\.__POSTHOG_PLAYER_CONFIG__ = ({.*?});/)
            expect(configMatch).toBeTruthy()
            // eslint-disable-next-line no-restricted-syntax
            const parsed = JSON.parse(configMatch![1])
            expect(parsed.startTimestamp).toBeUndefined()
            expect(parsed.endTimestamp).toBeUndefined()
        })

        it('passes skipInactivity=false when explicitly disabled', () => {
            const result = buildPlayerHtml(baseHtml, baseInput({ skip_inactivity: false }), 4, config)
            expect(result).toContain('"skipInactivity":false')
        })

        it('passes mouseTail=false when explicitly disabled', () => {
            const result = buildPlayerHtml(baseHtml, baseInput({ mouse_tail: false }), 4, config)
            expect(result).toContain('"mouseTail":false')
        })

        it('passes viewport events to player config', () => {
            const events = [{ timestamp: 1000, width: 1920, height: 1080 }]
            const result = buildPlayerHtml(baseHtml, baseInput({ viewport_events: events }), 4, config)
            expect(result).toContain('"viewportEvents":[{"timestamp":1000,"width":1920,"height":1080}]')
        })
    })
})
