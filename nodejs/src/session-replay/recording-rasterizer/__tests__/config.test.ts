import { buildCaptureConfig, buildPlayerConfig, validateInput } from '../capture/config'
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

describe('config', () => {
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
            { field: 'trim', value: 0, error: 'trim must be positive' },
            { field: 'trim', value: -5, error: 'trim must be positive' },
            { field: 'screenshot_quality', value: 0, error: 'screenshot_quality must be between 1 and 100' },
            { field: 'screenshot_quality', value: 101, error: 'screenshot_quality must be between 1 and 100' },
            { field: 'screenshot_quality', value: -1, error: 'screenshot_quality must be between 1 and 100' },
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

    describe('buildCaptureConfig', () => {
        describe('fps calculation', () => {
            it.each([
                { speed: 4, fps: 24, expectedCapture: 96 },
                { speed: 8, fps: 3, expectedCapture: 24 },
                { speed: 1, fps: 24, expectedCapture: 24 },
                { speed: 16, fps: 6, expectedCapture: 96 },
            ])('captureFps = $fps * $speed = $expectedCapture', ({ speed, fps, expectedCapture }) => {
                const config = buildCaptureConfig(baseInput({ playback_speed: speed, recording_fps: fps }))
                expect(config.captureFps).toBe(expectedCapture)
                expect(config.outputFps).toBe(fps)
            })

            it('defaults to 4x speed and 24fps', () => {
                const config = buildCaptureConfig(baseInput())
                expect(config.playbackSpeed).toBe(4)
                expect(config.outputFps).toBe(24)
                expect(config.captureFps).toBe(96)
            })
        })

        describe('trim', () => {
            it('sets trimFrameLimit based on trim and outputFps', () => {
                const config = buildCaptureConfig(baseInput({ trim: 40, recording_fps: 3 }))
                expect(config.trim).toBe(40)
                expect(config.trimFrameLimit).toBe(120) // 40 * 3
            })

            it('defaults trimFrameLimit to Infinity when no trim', () => {
                const config = buildCaptureConfig(baseInput())
                expect(config.trim).toBeUndefined()
                expect(config.trimFrameLimit).toBe(Infinity)
            })

            it('adds -t to ffmpeg output opts when trim is set', () => {
                const config = buildCaptureConfig(baseInput({ trim: 60 }))
                expect(config.ffmpegOutputOpts).toContain('-t 60')
            })

            it('does not add -t when trim is not set', () => {
                const config = buildCaptureConfig(baseInput())
                expect(config.ffmpegOutputOpts.some((o) => o.startsWith('-t '))).toBe(false)
            })
        })

        describe('capture timeout', () => {
            it('converts capture_timeout seconds to ms', () => {
                const config = buildCaptureConfig(baseInput({ capture_timeout: 300 }))
                expect(config.captureTimeoutMs).toBe(300_000)
            })

            it('defaults to Infinity when no capture_timeout', () => {
                const config = buildCaptureConfig(baseInput())
                expect(config.captureTimeoutMs).toBe(Infinity)
            })
        })

        describe('ffmpeg filters', () => {
            it('adds setpts and fps filters when playback speed > 1', () => {
                const config = buildCaptureConfig(baseInput({ playback_speed: 8 }))
                expect(config.ffmpegVideoFilters).toEqual(['setpts=8*PTS', 'fps=24'])
            })

            it('no video filters at 1x speed', () => {
                const config = buildCaptureConfig(baseInput({ playback_speed: 1 }))
                expect(config.ffmpegVideoFilters).toEqual([])
            })

            it('always includes baseline output opts', () => {
                const config = buildCaptureConfig(baseInput())
                expect(config.ffmpegOutputOpts).toContain('-crf 23')
                expect(config.ffmpegOutputOpts).toContain('-pix_fmt yuv420p')
                expect(config.ffmpegOutputOpts).toContain('-movflags +faststart')
            })

            it.each([
                { speed: 1.5, expected: ['setpts=1.5*PTS', 'fps=24'] },
                { speed: 2.5, expected: ['setpts=2.5*PTS', 'fps=24'] },
            ])('adds setpts and fps filters for fractional speed $speed', ({ speed, expected }) => {
                const config = buildCaptureConfig(baseInput({ playback_speed: speed }))
                expect(config.ffmpegVideoFilters).toEqual(expected)
            })
        })

        describe('edge cases', () => {
            it.each([
                { speed: 1.5, fps: 24, expectedCapture: 36 },
                { speed: 0.5, fps: 24, expectedCapture: 12 },
                { speed: 2.5, fps: 10, expectedCapture: 25 },
            ])('handles fractional playback_speed=$speed with fps=$fps', ({ speed, fps, expectedCapture }) => {
                const config = buildCaptureConfig(baseInput({ playback_speed: speed, recording_fps: fps }))
                expect(config.captureFps).toBe(expectedCapture)
                expect(config.playbackSpeed).toBe(speed)
            })

            it('handles very high playback speed', () => {
                const config = buildCaptureConfig(baseInput({ playback_speed: 100, recording_fps: 3 }))
                expect(config.captureFps).toBe(300)
                expect(config.ffmpegVideoFilters).toEqual(['setpts=100*PTS', 'fps=3'])
            })

            it('trim=1 produces trimFrameLimit equal to outputFps', () => {
                const config = buildCaptureConfig(baseInput({ trim: 1, recording_fps: 24 }))
                expect(config.trimFrameLimit).toBe(24)
            })
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
})
