import { scaleDimensionsIfNeeded, setupUrlForPlaybackSpeed, validateInput, validateRecordingUrl } from '../recorder'
import { RasterizeRecordingInput } from '../types'

function baseInput(overrides: Partial<RasterizeRecordingInput> = {}): RasterizeRecordingInput {
    return {
        recording_url: 'https://app.posthog.com/exporter?token=abc',
        wait_for_css_selector: '.replayer-wrapper',
        recording_duration: 10,
        playback_speed: 4,
        s3_bucket: 'test-bucket',
        s3_key_prefix: 'exports/mp4/team-1/task-1',
        ...overrides,
    }
}

describe('recorder', () => {
    describe('scaleDimensionsIfNeeded', () => {
        it.each([
            { width: 800, height: 600, expected: { width: 800, height: 600 }, desc: 'no scaling needed' },
            { width: 1920, height: 1080, expected: { width: 1920, height: 1080 }, desc: 'exactly at max' },
            {
                width: 3840,
                height: 2160,
                expected: { width: 1920, height: 1080 },
                desc: 'landscape scaled down',
            },
            {
                width: 1080,
                height: 3840,
                expected: { width: 540, height: 1920 },
                desc: 'portrait scaled down',
            },
            {
                width: 2560,
                height: 2560,
                expected: { width: 1920, height: 1920 },
                desc: 'square scaled down (height path)',
            },
            {
                width: 4000,
                height: 1000,
                expected: { width: 1920, height: 480 },
                desc: 'ultrawide scaled down',
            },
        ])('$desc (${width}x${height})', ({ width, height, expected }) => {
            expect(scaleDimensionsIfNeeded(width, height)).toEqual(expected)
        })

        it('respects custom maxSize', () => {
            expect(scaleDimensionsIfNeeded(2000, 1000, 1000)).toEqual({ width: 1000, height: 500 })
        })
    })

    describe('setupUrlForPlaybackSpeed', () => {
        it.each([
            {
                url: 'https://app.posthog.com/exporter?token=abc',
                speed: 8,
                expected: 'https://app.posthog.com/exporter?token=abc&playerSpeed=8',
            },
            {
                url: 'https://app.posthog.com/exporter?token=abc&playerSpeed=2',
                speed: 16,
                expected: 'https://app.posthog.com/exporter?token=abc&playerSpeed=16',
            },
        ])('sets playerSpeed=$speed on $url', ({ url, speed, expected }) => {
            expect(setupUrlForPlaybackSpeed(url, speed)).toBe(expected)
        })
    })

    describe('validateRecordingUrl', () => {
        it.each([
            'https://app.posthog.com/exporter?token=abc',
            'https://us.posthog.com/exporter?token=abc',
            'http://localhost:8000/exporter?token=abc',
            'https://custom.domain.com/exporter?token=abc&extra=1',
        ])('accepts valid URL: %s', (url) => {
            expect(() => validateRecordingUrl(url)).not.toThrow()
        })

        it.each([
            { url: 'file:///etc/passwd', reason: 'file scheme' },
            { url: 'ftp://example.com/exporter', reason: 'ftp scheme' },
            { url: 'https://169.254.169.254/latest/meta-data/', reason: 'no /exporter path' },
            { url: 'https://app.posthog.com/api/projects', reason: 'wrong path' },
            { url: 'https://internal-service.local/admin', reason: 'internal service' },
        ])('rejects $reason: $url', ({ url }) => {
            expect(() => validateRecordingUrl(url)).toThrow()
        })
    })

    describe('validateInput', () => {
        it('accepts valid input', () => {
            expect(() => validateInput(baseInput())).not.toThrow()
        })

        it.each([
            { field: 'playback_speed', value: 0, error: 'playback_speed must be positive' },
            { field: 'playback_speed', value: -1, error: 'playback_speed must be positive' },
            { field: 'recording_duration', value: 0, error: 'recording_duration must be positive' },
            { field: 'recording_duration', value: -5, error: 'recording_duration must be positive' },
            { field: 'recording_fps', value: 0, error: 'recording_fps must be positive' },
            { field: 'recording_fps', value: -10, error: 'recording_fps must be positive' },
        ])('rejects $field=$value', ({ field, value, error }) => {
            expect(() => validateInput(baseInput({ [field]: value }))).toThrow(error)
        })

        it('rejects SSRF URLs', () => {
            expect(() =>
                validateInput(baseInput({ recording_url: 'https://169.254.169.254/latest/meta-data/' }))
            ).toThrow()
        })
    })
})
