import { buildCaptureConfig } from '../capture/capture'
import { RasterizeRecordingInput } from '../types'

function baseInput(overrides: Partial<RasterizeRecordingInput> = {}): RasterizeRecordingInput {
    return {
        session_id: 'test-session',
        team_id: 1,
        s3_bucket: 'test-bucket',
        s3_key_prefix: 'test-prefix',
        ...overrides,
    }
}

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
