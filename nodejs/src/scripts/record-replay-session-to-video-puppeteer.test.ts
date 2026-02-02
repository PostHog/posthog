jest.mock('puppeteer', () => ({}))
jest.mock('puppeteer-screen-recorder', () => ({ PuppeteerScreenRecorder: jest.fn() }))

const {
    scaleDimensionsIfNeeded,
    setupUrlForPlaybackSpeed,
    waitForPageReady,
    waitForRecordingWithSegments,
    detectInactivityPeriods,
    MAX_DIMENSION,
    DEFAULT_WIDTH,
    DEFAULT_HEIGHT,
} = require('./record-replay-session-to-video-puppeteer')

describe('record-replay-session-to-video-puppeteer', () => {
    describe('constants', () => {
        it('has expected default values', () => {
            expect(MAX_DIMENSION).toBe(1920)
            expect(DEFAULT_WIDTH).toBe(1920)
            expect(DEFAULT_HEIGHT).toBe(1080)
        })
    })

    describe('scaleDimensionsIfNeeded', () => {
        it.each([
            [800, 600, 1920, 800, 600, 'returns original when both under max'],
            [1920, 600, 1920, 1920, 600, 'returns original when at max'],
            [3840, 600, 1920, 1920, 300, 'scales down when width exceeds max'],
            [600, 3840, 1920, 300, 1920, 'scales down when height exceeds max'],
            [3840, 2880, 1920, 1920, 1440, 'scales by width when width > height'],
            [2880, 3840, 1920, 1440, 1920, 'scales by height when height > width'],
            [3840, 3840, 1920, 1920, 1920, 'scales square dimensions correctly'],
            [100, 100, 1920, 100, 100, 'handles small dimensions'],
            [0, 0, 1920, 0, 0, 'handles zero dimensions'],
        ])('(%d, %d, %d) => (%d, %d) - %s', (width, height, maxSize, expectedWidth, expectedHeight) => {
            const result = scaleDimensionsIfNeeded(width, height, maxSize)
            expect(result).toEqual({ width: expectedWidth, height: expectedHeight })
        })

        it('uses MAX_DIMENSION as default maxSize', () => {
            const result = scaleDimensionsIfNeeded(3840, 600)
            expect(result).toEqual({ width: 1920, height: 300 })
        })
    })

    describe('setupUrlForPlaybackSpeed', () => {
        it.each([
            ['https://example.com/replay', 1, 'https://example.com/replay?playerSpeed=1'],
            ['https://example.com/replay', 4, 'https://example.com/replay?playerSpeed=4'],
            ['https://example.com/replay?foo=bar', 2, 'https://example.com/replay?foo=bar&playerSpeed=2'],
            ['https://example.com/replay?playerSpeed=1', 4, 'https://example.com/replay?playerSpeed=4'],
            ['https://example.com/replay#hash', 3, 'https://example.com/replay?playerSpeed=3#hash'],
        ])('setupUrlForPlaybackSpeed(%s, %d) => %s', (url, speed, expected) => {
            expect(setupUrlForPlaybackSpeed(url, speed)).toBe(expected)
        })

        it('handles float playback speeds', () => {
            const result = setupUrlForPlaybackSpeed('https://example.com/replay', 1.5)
            expect(result).toBe('https://example.com/replay?playerSpeed=1.5')
        })
    })

    describe('waitForPageReady', () => {
        let mockPage: {
            goto: jest.Mock
            waitForSelector: jest.Mock
        }

        beforeEach(() => {
            mockPage = {
                goto: jest.fn().mockResolvedValue(undefined),
                waitForSelector: jest.fn().mockResolvedValue(undefined),
            }
        })

        it('navigates to URL and waits for selectors', async () => {
            await waitForPageReady(mockPage, 'https://example.com', '.replayer-wrapper')

            expect(mockPage.goto).toHaveBeenCalledWith('https://example.com', { waitUntil: 'load', timeout: 30000 })
            expect(mockPage.waitForSelector).toHaveBeenCalledWith('.replayer-wrapper', {
                visible: true,
                timeout: 20000,
            })
            expect(mockPage.waitForSelector).toHaveBeenCalledWith('.Spinner', { hidden: true, timeout: 20000 })
        })

        it('throws when navigation fails', async () => {
            mockPage.goto.mockRejectedValue(new Error('Navigation timeout'))

            await expect(waitForPageReady(mockPage, 'https://example.com', '.replayer-wrapper')).rejects.toThrow(
                'Navigation timeout'
            )
        })

        it('continues when selector wait times out', async () => {
            mockPage.waitForSelector.mockRejectedValue(new Error('Selector timeout'))

            await expect(
                waitForPageReady(mockPage, 'https://example.com', '.replayer-wrapper')
            ).resolves.toBeUndefined()
        })

        it('continues when spinner wait times out', async () => {
            mockPage.waitForSelector
                .mockResolvedValueOnce(undefined) // .replayer-wrapper succeeds
                .mockRejectedValueOnce(new Error('Spinner timeout')) // .Spinner fails

            await expect(
                waitForPageReady(mockPage, 'https://example.com', '.replayer-wrapper')
            ).resolves.toBeUndefined()
        })
    })

    describe('waitForRecordingWithSegments', () => {
        function mockHandle(value: any) {
            return { jsonValue: jest.fn().mockResolvedValue(value) }
        }

        let mockPage: { waitForFunction: jest.Mock }

        beforeEach(() => {
            mockPage = {
                waitForFunction: jest.fn(),
            }
        })

        it('returns empty segments when recording ends immediately', async () => {
            mockPage.waitForFunction.mockResolvedValue(mockHandle({ ended: true }))

            const result = await waitForRecordingWithSegments(mockPage, 5000, Date.now())

            expect(result).toEqual({})
        })

        it('tracks segment changes during recording', async () => {
            mockPage.waitForFunction
                .mockResolvedValueOnce(mockHandle({ counter: 1, segment_start_ts: 0 }))
                .mockResolvedValueOnce(mockHandle({ counter: 2, segment_start_ts: 10 }))
                .mockResolvedValueOnce(mockHandle({ ended: true }))

            const result = await waitForRecordingWithSegments(mockPage, 10000, Date.now())

            expect(Object.keys(result).length).toBe(2)
            expect(result[0]).toBeDefined()
            expect(result[10]).toBeDefined()
        })

        it('passes updated lastCounter to waitForFunction', async () => {
            mockPage.waitForFunction
                .mockResolvedValueOnce(mockHandle({ counter: 1, segment_start_ts: 0 }))
                .mockResolvedValueOnce(mockHandle({ ended: true }))

            await waitForRecordingWithSegments(mockPage, 10000, Date.now())

            expect(mockPage.waitForFunction.mock.calls[0][2]).toBe(0)
            expect(mockPage.waitForFunction.mock.calls[1][2]).toBe(1)
        })

        it('uses raf polling with remaining time as timeout', async () => {
            mockPage.waitForFunction.mockResolvedValue(mockHandle({ ended: true }))

            await waitForRecordingWithSegments(mockPage, 5000, Date.now())

            const options = mockPage.waitForFunction.mock.calls[0][1]
            expect(options.polling).toBe('raf')
            expect(options.timeout).toBeGreaterThan(0)
            expect(options.timeout).toBeLessThanOrEqual(5000)
        })

        it('stops when waitForFunction times out', async () => {
            mockPage.waitForFunction.mockRejectedValue(new Error('Timeout'))

            const result = await waitForRecordingWithSegments(mockPage, 10000, Date.now())

            expect(result).toEqual({})
        })

        it('stops without calling waitForFunction when maxWaitMs already elapsed', async () => {
            const result = await waitForRecordingWithSegments(mockPage, 1000, Date.now() - 2000)

            expect(result).toEqual({})
            expect(mockPage.waitForFunction).not.toHaveBeenCalled()
        })
    })

    describe('detectInactivityPeriods', () => {
        let mockPage: { evaluate: jest.Mock }

        beforeEach(() => {
            mockPage = {
                evaluate: jest.fn(),
            }
        })

        it('returns empty array when no inactivity periods', async () => {
            mockPage.evaluate.mockResolvedValue([])

            const result = await detectInactivityPeriods(mockPage, 1, {})

            expect(result).toEqual([])
        })

        it('parses inactivity periods from window.__POSTHOG_INACTIVITY_PERIODS__', async () => {
            mockPage.evaluate.mockResolvedValue([
                { ts_from_s: 0, ts_to_s: 5, active: true },
                { ts_from_s: 5, ts_to_s: 10, active: false },
            ])

            const result = await detectInactivityPeriods(mockPage, 1, {})

            expect(result).toEqual([
                { ts_from_s: 0, ts_to_s: 5, active: true },
                { ts_from_s: 5, ts_to_s: 10, active: false },
            ])
        })

        it('handles null ts_to_s values', async () => {
            mockPage.evaluate.mockResolvedValue([{ ts_from_s: 0, ts_to_s: null, active: true }])

            const result = await detectInactivityPeriods(mockPage, 1, {})

            expect(result).toEqual([{ ts_from_s: 0, ts_to_s: null, active: true }])
        })

        it('merges segment timestamps and computes recording_ts_to_s', async () => {
            mockPage.evaluate.mockResolvedValue([
                { ts_from_s: 0, ts_to_s: 5, active: true },
                { ts_from_s: 10, ts_to_s: 15, active: false },
            ])

            const segmentStartTimestamps = { 0: 1.5, 10: 3.0 }

            const result = await detectInactivityPeriods(mockPage, 2, segmentStartTimestamps)

            expect(result).toEqual([
                { ts_from_s: 0, ts_to_s: 5, active: true, recording_ts_from_s: 3, recording_ts_to_s: 8 },
                { ts_from_s: 10, ts_to_s: 15, active: false, recording_ts_from_s: 6, recording_ts_to_s: 11 },
            ])
        })

        it('applies playback speed multiplier to recording timestamps', async () => {
            mockPage.evaluate.mockResolvedValue([{ ts_from_s: 5, ts_to_s: 10, active: false }])

            const segmentStartTimestamps = { 5: 2.5 }

            const result = await detectInactivityPeriods(mockPage, 4, segmentStartTimestamps)

            expect(result[0].recording_ts_from_s).toBe(10) // 2.5 * 4
            expect(result[0].recording_ts_to_s).toBe(15) // 10 + (10 - 5)
        })

        it('returns null when evaluate throws', async () => {
            mockPage.evaluate.mockRejectedValue(new Error('Evaluation failed'))

            const result = await detectInactivityPeriods(mockPage, 1, {})

            expect(result).toBeNull()
        })

        it('skips periods without matching segment timestamps', async () => {
            mockPage.evaluate.mockResolvedValue([
                { ts_from_s: 0, ts_to_s: 5, active: true },
                { ts_from_s: 10, ts_to_s: 15, active: false },
            ])

            const segmentStartTimestamps = { 0: 1.5 }

            const result = await detectInactivityPeriods(mockPage, 1, segmentStartTimestamps)

            expect(result[0].recording_ts_from_s).toBe(1.5) // 1.5 * 1
            expect(result[0].recording_ts_to_s).toBe(6.5) // 1.5 + (5 - 0)
            expect(result[1].recording_ts_from_s).toBeUndefined()
            expect(result[1].recording_ts_to_s).toBeUndefined()
        })
    })
})
