import * as fs from 'fs/promises'
import * as os from 'os'
import * as path from 'path'

import { capturePlayback } from '../capture/capture'
import { PlayerController } from '../capture/player'
import { RasterizationError } from '../errors'
import { CaptureConfig } from '../types'

jest.mock(
    'puppeteer-capture',
    () => {
        const recorder = {
            start: jest.fn().mockResolvedValue(undefined),
            stop: jest.fn().mockResolvedValue(undefined),
            waitForTimeout: jest.fn().mockResolvedValue(undefined),
            on: jest.fn(),
        }
        return {
            __mockRecorder: recorder,
            PuppeteerCaptureFormat: { MP4: jest.fn().mockReturnValue('mp4-format') },
            capture: jest.fn().mockResolvedValue(recorder),
        }
    },
    { virtual: true }
)

jest.mock('../logger', () => ({
    createLogger: () => ({
        info: jest.fn(),
        warn: jest.fn(),
        error: jest.fn(),
        debug: jest.fn(),
        child: jest.fn().mockReturnThis(),
    }),
}))

const { __mockRecorder: mockRecorder } = require('puppeteer-capture')

function baseCaptureConfig(overrides: Partial<CaptureConfig> = {}): CaptureConfig {
    return {
        captureFps: 24,
        outputFps: 3,
        playbackSpeed: 8,
        trimFrameLimit: Infinity,
        captureTimeoutMs: Infinity,
        ffmpegOutputOpts: [],
        ffmpegVideoFilters: [],
        screenshotFormat: 'jpeg',
        screenshotQuality: 80,
        ...overrides,
    }
}

const mockPage = {
    viewport: jest.fn().mockReturnValue({ width: 1920, height: 1080 }),
    on: jest.fn(),
} as any

function mockPlayer(overrides: Partial<Record<keyof PlayerController, any>> = {}): PlayerController {
    return {
        page: mockPage,
        prepareBrowserForCapture: jest.fn(),
        startPlayback: jest.fn().mockResolvedValue(undefined),
        isEnded: jest.fn().mockReturnValue(false),
        getError: jest.fn().mockReturnValue(null),
        getInactivityPeriods: jest.fn().mockReturnValue([]),
        waitForSettled: jest.fn().mockResolvedValue(undefined),
        ...overrides,
    } as unknown as PlayerController
}

describe('capturePlayback', () => {
    let outputPath: string

    beforeEach(async () => {
        jest.clearAllMocks()
        outputPath = path.join(os.tmpdir(), `test-capture-${Date.now()}.mp4`)
        // Create a dummy file so fs.stat succeeds
        await fs.writeFile(outputPath, Buffer.alloc(64))

        // Reset recorder behavior
        mockRecorder.start.mockResolvedValue(undefined)
        mockRecorder.stop.mockResolvedValue(undefined)
        mockRecorder.on.mockImplementation(() => {})
        mockRecorder.waitForTimeout.mockResolvedValue(undefined)
    })

    afterEach(async () => {
        await fs.rm(outputPath, { force: true })
    })

    function simulateFrames(count: number): void {
        // Find the frameCaptured callback and call it count times
        const onCall = mockRecorder.on.mock.calls.find(([event]: [string]) => event === 'frameCaptured')
        if (onCall) {
            const callback = onCall[1]
            for (let i = 0; i < count; i++) {
                callback()
            }
        }
    }

    it('stops when player signals ended', async () => {
        let iteration = 0
        const player = mockPlayer({
            isEnded: jest.fn().mockImplementation(() => {
                iteration++
                return iteration >= 3
            }),
        })

        mockRecorder.waitForTimeout.mockImplementation(() => {
            simulateFrames(3)
        })

        const result = await capturePlayback(player, baseCaptureConfig(), outputPath)

        expect(mockRecorder.start).toHaveBeenCalledWith(outputPath)
        expect(mockRecorder.stop).toHaveBeenCalled()
        expect(player.startPlayback).toHaveBeenCalled()
        expect(result.capture_duration_s).toBeGreaterThanOrEqual(0)
    })

    it('stops when trim frame limit is reached', async () => {
        const player = mockPlayer()

        mockRecorder.waitForTimeout.mockImplementation(() => {
            simulateFrames(50)
        })

        const config = baseCaptureConfig({ trim: 10, trimFrameLimit: 30, outputFps: 3 })
        const result = await capturePlayback(player, config, outputPath)

        expect(mockRecorder.stop).toHaveBeenCalled()
        expect(result.capture_duration_s).toBeLessThanOrEqual(10)
    })

    it('stops when capture timeout is reached', async () => {
        const player = mockPlayer()

        mockRecorder.waitForTimeout.mockImplementation(() => {})

        const config = baseCaptureConfig({ captureTimeoutMs: 3000 })
        await capturePlayback(player, config, outputPath)

        expect(mockRecorder.stop).toHaveBeenCalled()
    })

    it('calls recorder.stop even if loop throws', async () => {
        const player = mockPlayer({
            startPlayback: jest.fn().mockRejectedValue(new Error('playback failed')),
        })

        await expect(capturePlayback(player, baseCaptureConfig(), outputPath)).rejects.toThrow('playback failed')
        expect(mockRecorder.stop).toHaveBeenCalled()
    })

    it('handles recorder.stop failure gracefully', async () => {
        const player = mockPlayer({ isEnded: jest.fn().mockReturnValue(true) })
        mockRecorder.stop.mockRejectedValue(new Error('ffmpeg crashed'))

        // Should not throw — the stop error is swallowed
        const result = await capturePlayback(player, baseCaptureConfig(), outputPath)
        expect(result).toBeDefined()
    })

    it('returns inactivity periods from player', async () => {
        const periods = [
            { ts_from_s: 0, ts_to_s: 5, active: true },
            { ts_from_s: 5, ts_to_s: 10, active: false },
        ]
        const player = mockPlayer({
            isEnded: jest.fn().mockReturnValue(true),
            getInactivityPeriods: jest.fn().mockReturnValue(periods),
        })

        const result = await capturePlayback(player, baseCaptureConfig(), outputPath)
        expect(result.inactivity_periods).toEqual(periods)
    })

    it('computes duration from frame count and outputFps', async () => {
        const player = mockPlayer()
        let iteration = 0

        mockRecorder.waitForTimeout.mockImplementation(() => {
            simulateFrames(9) // 9 frames per iteration
            iteration++
            if (iteration >= 2) {
                ;(player.isEnded as jest.Mock).mockReturnValue(true)
            }
        })

        const config = baseCaptureConfig({ outputFps: 3 })
        const result = await capturePlayback(player, config, outputPath)

        // 18 frames / 3 fps = 6 seconds
        expect(result.capture_duration_s).toBe(6)
    })

    it('returns truncated=false when recording ends normally', async () => {
        const player = mockPlayer({ isEnded: jest.fn().mockReturnValue(true) })
        const result = await capturePlayback(player, baseCaptureConfig(), outputPath)
        expect(result.truncated).toBe(false)
    })

    it('returns truncated=true when capture timeout is reached', async () => {
        const player = mockPlayer()
        mockRecorder.waitForTimeout.mockImplementation(() => {})

        const config = baseCaptureConfig({ captureTimeoutMs: 3000 })
        const result = await capturePlayback(player, config, outputPath)
        expect(result.truncated).toBe(true)
    })

    it('calls onProgress at progressInterval frame boundaries', async () => {
        const player = mockPlayer()
        const onProgress = jest.fn()
        let iteration = 0

        // captureFps=24, so progressInterval = max(10, 24) = 24
        // Simulate 72 frames over 3 iterations (24 per iteration)
        mockRecorder.waitForTimeout.mockImplementation(() => {
            simulateFrames(24)
            iteration++
            if (iteration >= 3) {
                ;(player.isEnded as jest.Mock).mockReturnValue(true)
            }
        })

        const config = baseCaptureConfig({ captureFps: 24 })
        await capturePlayback(player, config, outputPath, undefined, onProgress)

        // 72 frames / 24 interval = 3 calls
        expect(onProgress).toHaveBeenCalledTimes(3)
    })

    it('does not call onProgress before progressInterval is reached', async () => {
        const player = mockPlayer({ isEnded: jest.fn().mockReturnValue(true) })
        const onProgress = jest.fn()

        // Only 5 frames — below progressInterval of max(10, 24) = 24
        mockRecorder.waitForTimeout.mockImplementation(() => {
            simulateFrames(5)
        })

        const config = baseCaptureConfig({ captureFps: 24 })
        await capturePlayback(player, config, outputPath, undefined, onProgress)

        expect(onProgress).not.toHaveBeenCalled()
    })

    it('throws when player reports an error during capture', async () => {
        const player = mockPlayer()
        let iteration = 0

        mockRecorder.waitForTimeout.mockImplementation(() => {
            iteration++
            if (iteration >= 2) {
                ;(player.getError as jest.Mock).mockReturnValue(
                    new RasterizationError('[PLAYBACK_ERROR] something broke', true)
                )
            }
        })

        await expect(capturePlayback(player, baseCaptureConfig(), outputPath)).rejects.toThrow('something broke')
        expect(mockRecorder.stop).toHaveBeenCalled()
    })
})
