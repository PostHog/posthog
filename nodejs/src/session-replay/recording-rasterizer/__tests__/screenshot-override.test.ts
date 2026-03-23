import { CDPSession, Page } from 'puppeteer'

import { CaptureConfig, capturePlayback } from '../capture/capture'
import { PlayerController } from '../capture/player'

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

jest.mock('../config', () => ({
    config: {
        screenshotFormat: 'jpeg',
        screenshotJpegQuality: 80,
    },
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
        ...overrides,
    }
}

function mockPlayer(): PlayerController {
    return {
        startPlayback: jest.fn().mockResolvedValue(undefined),
        isEnded: jest.fn().mockReturnValue(true),
        getError: jest.fn().mockReturnValue(null),
        getInactivityPeriods: jest.fn().mockReturnValue([]),
    } as unknown as PlayerController
}

describe('overrideScreenshotFormat', () => {
    let originalSend: jest.Mock

    function createMockPage(): Page {
        originalSend = jest.fn().mockResolvedValue({ data: 'frame-data' })
        const mockSession = { send: originalSend } as unknown as CDPSession

        return {
            viewport: jest.fn().mockReturnValue({ width: 1280, height: 720 }),
            createCDPSession: jest.fn().mockResolvedValue(mockSession),
        } as unknown as Page
    }

    beforeEach(() => {
        jest.clearAllMocks()
        mockRecorder.start.mockResolvedValue(undefined)
        mockRecorder.stop.mockResolvedValue(undefined)
        mockRecorder.on.mockImplementation(() => {})
        mockRecorder.waitForTimeout.mockResolvedValue(undefined)
    })

    it('injects jpeg format and quality into beginFrame calls', async () => {
        const page = createMockPage()

        // capturePlayback calls overrideScreenshotFormat when config.screenshotFormat !== 'png'
        // which wraps page.createCDPSession. Then puppeteer-capture calls createCDPSession
        // internally and uses session.send for beginFrame.
        // We verify the wrapping by checking what createCDPSession returns after capturePlayback runs.

        // Use captureTimeoutMs=0 to exit loop immediately
        await capturePlayback(page, mockPlayer(), baseCaptureConfig({ captureTimeoutMs: 1 }), '/tmp/test.mp4')

        // After overrideScreenshotFormat, page.createCDPSession should be replaced
        const session = await (page as any).createCDPSession()
        await session.send('HeadlessExperimental.beginFrame', { deadline: 1000 })

        // The original send should have been called with injected screenshot params
        expect(originalSend).toHaveBeenCalledWith('HeadlessExperimental.beginFrame', {
            deadline: 1000,
            screenshot: { format: 'jpeg', quality: 80 },
        })
    })

    it('passes non-beginFrame CDP calls through unchanged', async () => {
        const page = createMockPage()

        await capturePlayback(page, mockPlayer(), baseCaptureConfig({ captureTimeoutMs: 1 }), '/tmp/test.mp4')

        const session = await (page as any).createCDPSession()
        await session.send('Page.navigate', { url: 'http://example.com' })

        expect(originalSend).toHaveBeenCalledWith('Page.navigate', { url: 'http://example.com' })
    })

    it('adds screenshot params even when beginFrame has no existing params', async () => {
        const page = createMockPage()

        await capturePlayback(page, mockPlayer(), baseCaptureConfig({ captureTimeoutMs: 1 }), '/tmp/test.mp4')

        const session = await (page as any).createCDPSession()
        await session.send('HeadlessExperimental.beginFrame')

        expect(originalSend).toHaveBeenCalledWith('HeadlessExperimental.beginFrame', {
            screenshot: { format: 'jpeg', quality: 80 },
        })
    })

    it('does not override when config is png', async () => {
        // Re-mock config with png
        const { config } = require('../config')
        const origFormat = config.screenshotFormat
        config.screenshotFormat = 'png'

        try {
            const page = createMockPage()
            const origCreateCDP = page.createCDPSession

            await capturePlayback(page, mockPlayer(), baseCaptureConfig({ captureTimeoutMs: 1 }), '/tmp/test.mp4')

            // createCDPSession should NOT have been wrapped
            expect(page.createCDPSession).toBe(origCreateCDP)
        } finally {
            config.screenshotFormat = origFormat
        }
    })
})
