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
            { field: 'max_virtual_time', value: 0, error: 'max_virtual_time must be positive' },
            { field: 'max_virtual_time', value: -5, error: 'max_virtual_time must be positive' },
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
            it('converts max_virtual_time seconds to ms', () => {
                const config = buildCaptureConfig(baseInput({ max_virtual_time: 300 }))
                expect(config.maxVirtualTimeMs).toBe(300_000)
            })

            it('defaults to Infinity when no max_virtual_time', () => {
                const config = buildCaptureConfig(baseInput())
                expect(config.maxVirtualTimeMs).toBe(Infinity)
            })
        })

        describe('ffmpeg filters', () => {
            it('adds setpts and fps filters when playback speed > 1', () => {
                const config = buildCaptureConfig(baseInput({ playback_speed: 8 }))
                expect(config.ffmpegVideoFilters).toEqual(['pad=ceil(iw/2)*2:ceil(ih/2)*2', 'setpts=8*PTS', 'fps=24'])
            })

            it('pads to even dimensions at 1x speed', () => {
                const config = buildCaptureConfig(baseInput({ playback_speed: 1 }))
                expect(config.ffmpegVideoFilters).toEqual(['pad=ceil(iw/2)*2:ceil(ih/2)*2'])
            })

            it('includes MP4 baseline output opts by default', () => {
                const config = buildCaptureConfig(baseInput())
                expect(config.outputFormat).toBe('mp4')
                expect(config.ffmpegOutputOpts).toContain('-f mp4')
                expect(config.ffmpegOutputOpts).toContain('-c:v libx264')
                expect(config.ffmpegOutputOpts).toContain('-preset veryfast')
                expect(config.ffmpegOutputOpts).toContain('-crf 23')
                expect(config.ffmpegOutputOpts).toContain('-pix_fmt yuv420p')
                expect(config.ffmpegOutputOpts).toContain('-movflags +faststart')
            })

            it('uses VP9 output opts for WebM format', () => {
                const config = buildCaptureConfig(baseInput({ output_format: 'webm' }))
                expect(config.outputFormat).toBe('webm')
                expect(config.ffmpegOutputOpts).toContain('-f webm')
                expect(config.ffmpegOutputOpts).toContain('-c:v libvpx-vp9')
                expect(config.ffmpegOutputOpts).toContain('-crf 30')
                expect(config.ffmpegOutputOpts).toContain('-b:v 0')
                expect(config.ffmpegOutputOpts).not.toContain('-movflags +faststart')
            })

            it('adds trim to WebM output opts', () => {
                const config = buildCaptureConfig(baseInput({ output_format: 'webm', trim: 30 }))
                expect(config.ffmpegOutputOpts).toContain('-t 30')
                expect(config.ffmpegOutputOpts).toContain('-c:v libvpx-vp9')
            })

            it('uses GIF output opts with palette generation', () => {
                const config = buildCaptureConfig(baseInput({ output_format: 'gif' }))
                expect(config.outputFormat).toBe('gif')
                expect(config.ffmpegOutputOpts).toContain('-f gif')
                expect(config.ffmpegOutputOpts).toContain('-c:v gif')
                expect(config.ffmpegOutputOpts).toContain('-loop')
                expect(config.ffmpegOutputOpts).toContain('0')
                expect(config.ffmpegOutputOpts).not.toContain('-movflags +faststart')
                expect(config.ffmpegVideoFilters).not.toContain('pad=ceil(iw/2)*2:ceil(ih/2)*2')
                expect(config.ffmpegVideoFilters).toContain('scale=800:-2:flags=lanczos')
                expect(config.ffmpegVideoFilters).toContain('fps=12')
                expect(config.ffmpegVideoFilters).toContain(
                    'split[s0][s1];[s0]palettegen=stats_mode=single[p];[s1][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle'
                )
            })

            it.each([
                { speed: 1.5, expected: ['pad=ceil(iw/2)*2:ceil(ih/2)*2', 'setpts=1.5*PTS', 'fps=24'] },
                { speed: 2.5, expected: ['pad=ceil(iw/2)*2:ceil(ih/2)*2', 'setpts=2.5*PTS', 'fps=24'] },
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
                expect(config.ffmpegVideoFilters).toEqual(['pad=ceil(iw/2)*2:ceil(ih/2)*2', 'setpts=100*PTS', 'fps=3'])
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

        it('passes startOffsetS and endOffsetS', () => {
            const result = buildPlayerConfig(baseInput({ start_offset_s: 10, end_offset_s: 70 }), 4, 5)
            expect(result.startOffsetS).toBe(10)
            expect(result.endOffsetS).toBe(70)
        })

        it('omits startOffsetS and endOffsetS when not provided', () => {
            const result = buildPlayerConfig(baseInput(), 4, 5)
            expect(result.startOffsetS).toBeUndefined()
            expect(result.endOffsetS).toBeUndefined()
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
