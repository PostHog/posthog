import { BlockProxy } from '~/session-replay/recording-rasterizer/capture/block-proxy'
import { BrowserPool } from '~/session-replay/recording-rasterizer/capture/browser-pool'
import { capturePlayback } from '~/session-replay/recording-rasterizer/capture/capture'
import { CapturePage } from '~/session-replay/recording-rasterizer/capture/capture-page'
import { PlayerController } from '~/session-replay/recording-rasterizer/capture/player'
import { rasterizeRecording } from '~/session-replay/recording-rasterizer/capture/recorder'
import { RasterizeRecordingInput } from '~/session-replay/recording-rasterizer/types'

jest.mock('~/session-replay/recording-rasterizer/capture/capture')
jest.mock('~/session-replay/recording-rasterizer/capture/capture-page')
jest.mock('~/session-replay/recording-rasterizer/capture/block-proxy')
jest.mock('~/session-replay/recording-rasterizer/capture/player')
jest.mock('~/session-replay/recording-rasterizer/logger', () => ({
    createLogger: () => ({
        info: jest.fn(),
        warn: jest.fn(),
        error: jest.fn(),
        debug: jest.fn(),
        child: jest.fn().mockReturnThis(),
    }),
}))

const mockedCapturePage = CapturePage as jest.Mocked<typeof CapturePage>
const mockedBlockProxy = BlockProxy as jest.MockedClass<typeof BlockProxy>
const mockedPlayerController = PlayerController as jest.MockedClass<typeof PlayerController>
const mockedCapturePlayback = capturePlayback as jest.MockedFunction<typeof capturePlayback>

const mockPage = {} as any
const mockCapturePage = { page: mockPage } as unknown as CapturePage

function baseInput(overrides: Partial<RasterizeRecordingInput> = {}): RasterizeRecordingInput {
    return {
        session_id: 'test-session',
        team_id: 1,
        playback_speed: 4,
        s3_bucket: 'bucket',
        s3_key_prefix: 'prefix',
        ...overrides,
    }
}

const baseCaptureResult = {
    capture_duration_s: 5,
    frame_count: 120,
    truncated: false,
    inactivity_periods: [],
    timings: { setup_s: 0, capture_s: 2.5 },
}

const cfg = {
    siteUrl: 'http://localhost:8000',
    captureBrowserLogs: false,
    recordingApiBaseUrl: 'http://localhost:6738',
    recordingApiSecret: 'secret',
    screenshotFormat: 'jpeg' as const,
    screenshotJpegQuality: 80,
    maxRecordingCompressedBytes: 512 * 1024 * 1024,
} as any

describe('rasterizeRecording', () => {
    let mockPool: BrowserPool
    let mockPlayer: jest.Mocked<PlayerController>

    beforeEach(() => {
        jest.clearAllMocks()

        mockPool = {
            getPage: jest.fn().mockResolvedValue(mockPage),
            releasePage: jest.fn().mockResolvedValue(undefined),
        } as unknown as BrowserPool

        mockedCapturePage.prepare = jest.fn().mockResolvedValue(mockCapturePage)

        mockedBlockProxy.prototype.fetchBlocks = jest.fn().mockResolvedValue(3)
        // The automock drops the getter, and `undefined > cap` would silently disable the size gate.
        Object.defineProperty(mockedBlockProxy.prototype, 'totalCompressedBytes', {
            get: () => 1024,
            configurable: true,
        })

        mockPlayer = {
            load: jest.fn().mockResolvedValue(undefined),
            waitForStart: jest.fn().mockResolvedValue(undefined),
            dispose: jest.fn(),
        } as unknown as jest.Mocked<PlayerController>
        mockedPlayerController.mockImplementation(() => mockPlayer)

        mockedCapturePlayback.mockResolvedValue(baseCaptureResult)
    })

    it('calls modules in the correct order', async () => {
        const callOrder: string[] = []
        ;(mockPool.getPage as jest.Mock).mockImplementation(() => {
            callOrder.push('getPage')
            return Promise.resolve(mockPage)
        })
        mockedCapturePage.prepare = jest.fn().mockImplementation(() => {
            callOrder.push('prepare')
            return Promise.resolve(mockCapturePage)
        })
        mockedBlockProxy.prototype.fetchBlocks = jest.fn().mockImplementation(() => {
            callOrder.push('fetchBlocks')
            return Promise.resolve(3)
        })
        mockPlayer.load.mockImplementation(() => {
            callOrder.push('load')
            return Promise.resolve()
        })
        mockPlayer.waitForStart.mockImplementation(() => {
            callOrder.push('waitForStart')
            return Promise.resolve()
        })
        mockedCapturePlayback.mockImplementation(() => {
            callOrder.push('capturePlayback')
            return Promise.resolve(baseCaptureResult)
        })

        await rasterizeRecording(mockPool, baseInput(), '/tmp/out.mp4', '<html></html>', jest.fn(), { cfg })

        expect(callOrder).toEqual(['getPage', 'prepare', 'fetchBlocks', 'load', 'waitForStart', 'capturePlayback'])
    })

    it('fails permanently before loading when the listing exceeds the byte cap', async () => {
        Object.defineProperty(mockedBlockProxy.prototype, 'totalCompressedBytes', {
            get: () => cfg.maxRecordingCompressedBytes + 1,
            configurable: true,
        })

        await expect(
            rasterizeRecording(mockPool, baseInput(), '/tmp/out.mp4', '<html></html>', jest.fn(), { cfg })
        ).rejects.toMatchObject({ code: 'RECORDING_TOO_LARGE', retryable: false })

        expect(mockPlayer.load).not.toHaveBeenCalled()
        expect(mockPool.releasePage).toHaveBeenCalledWith(mockPage)
    })

    it('releases page and disposes player on success', async () => {
        await rasterizeRecording(mockPool, baseInput(), '/tmp/out.mp4', '<html></html>', jest.fn(), { cfg })

        expect(mockPlayer.dispose).toHaveBeenCalled()
        expect(mockPool.releasePage).toHaveBeenCalledWith(mockPage)
    })

    it('releases page and disposes player when capturePlayback throws', async () => {
        mockedCapturePlayback.mockRejectedValue(new Error('capture failed'))

        await expect(
            rasterizeRecording(mockPool, baseInput(), '/tmp/out.mp4', '<html></html>', jest.fn(), { cfg })
        ).rejects.toThrow('capture failed')

        expect(mockPlayer.dispose).toHaveBeenCalled()
        expect(mockPool.releasePage).toHaveBeenCalledWith(mockPage)
    })

    it('releases page when player.load throws (before player is assigned)', async () => {
        mockPlayer.load.mockRejectedValue(new Error('navigation failed'))

        await expect(
            rasterizeRecording(mockPool, baseInput(), '/tmp/out.mp4', '<html></html>', jest.fn(), { cfg })
        ).rejects.toThrow('navigation failed')

        expect(mockPool.releasePage).toHaveBeenCalledWith(mockPage)
    })

    it('releases page when BlockProxy.fetchBlocks throws', async () => {
        mockedBlockProxy.prototype.fetchBlocks = jest.fn().mockRejectedValue(new Error('API down'))

        await expect(
            rasterizeRecording(mockPool, baseInput(), '/tmp/out.mp4', '<html></html>', jest.fn(), { cfg })
        ).rejects.toThrow('API down')

        expect(mockPool.releasePage).toHaveBeenCalledWith(mockPage)
    })

    it('passes playerHtml to CapturePage.prepare', async () => {
        await rasterizeRecording(mockPool, baseInput(), '/tmp/out.mp4', '<html>player</html>', jest.fn(), { cfg })

        expect(mockedCapturePage.prepare).toHaveBeenCalledWith(
            mockPage,
            expect.any(Object),
            'http://localhost:8000/player',
            '<html>player</html>',
            false,
            expect.any(Object)
        )
    })

    it('uses input viewport dimensions with defaults', async () => {
        await rasterizeRecording(
            mockPool,
            baseInput({ viewport_width: 1920, viewport_height: 1080 }),
            '/tmp/out.mp4',
            '<html></html>',
            jest.fn(),
            { cfg }
        )

        expect(mockedCapturePage.prepare).toHaveBeenCalledWith(
            mockPage,
            { width: 1920, height: 1080 },
            expect.any(String),
            expect.any(String),
            expect.any(Boolean),
            expect.any(Object)
        )
    })

    it('defaults viewport to 1280x720', async () => {
        await rasterizeRecording(mockPool, baseInput(), '/tmp/out.mp4', '<html></html>', jest.fn(), { cfg })

        expect(mockedCapturePage.prepare).toHaveBeenCalledWith(
            mockPage,
            { width: 1280, height: 720 },
            expect.any(String),
            expect.any(String),
            expect.any(Boolean),
            expect.any(Object)
        )
    })

    it('returns RecordingResult with fields from capturePlayback', async () => {
        const result = await rasterizeRecording(
            mockPool,
            baseInput({ playback_speed: 8 }),
            '/tmp/out.mp4',
            '<html></html>',
            jest.fn(),
            { cfg }
        )

        expect(result.playback_speed).toBe(8)
        expect(result.capture_duration_s).toBe(5)
        expect(result.frame_count).toBe(120)
        expect(result.truncated).toBe(false)
        expect(result.timings.capture_s).toBe(2.5)
        expect(result.timings.setup_s).toBeGreaterThanOrEqual(0)
    })

    it('throws before taking a page when the signal is already aborted', async () => {
        const controller = new AbortController()
        controller.abort()

        await expect(
            rasterizeRecording(mockPool, baseInput(), '/tmp/out.mp4', '<html></html>', jest.fn(), {
                cfg,
                signal: controller.signal,
            })
        ).rejects.toThrow()
        expect(mockPool.getPage).not.toHaveBeenCalled()
    })

    it('closes the page when the signal aborts mid-render', async () => {
        // Closing the page is what unsticks a wedged CDP send and frees the pool slot; without it a
        // cancelled activity keeps rendering to completion.
        const pageWithClose = { close: jest.fn().mockResolvedValue(undefined) } as any
        ;(mockPool.getPage as jest.Mock).mockResolvedValue(pageWithClose)
        const controller = new AbortController()
        mockedCapturePlayback.mockImplementation(() => {
            controller.abort()
            return Promise.reject(new Error('capture aborted'))
        })

        await expect(
            rasterizeRecording(mockPool, baseInput(), '/tmp/out.mp4', '<html></html>', jest.fn(), {
                cfg,
                signal: controller.signal,
            })
        ).rejects.toThrow('capture aborted')
        expect(pageWithClose.close).toHaveBeenCalled()
    })

    it('calls onProgress after waitForStart', async () => {
        const onProgress = jest.fn()

        await rasterizeRecording(mockPool, baseInput(), '/tmp/out.mp4', '<html></html>', onProgress, { cfg })

        expect(onProgress).toHaveBeenCalledTimes(1)
    })
})
