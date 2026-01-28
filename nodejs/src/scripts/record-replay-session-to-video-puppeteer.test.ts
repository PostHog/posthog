const {
    scaleDimensionsIfNeeded,
    ensurePlaybackSpeed,
    waitForPageReady,
    detectRecordingResolution,
    waitForRecordingWithSegments,
    detectInactivityPeriods,
    HEIGHT_OFFSET,
    PLAYBACK_SPEED_MULTIPLIER,
    MAX_DIMENSION,
    DEFAULT_WIDTH,
    DEFAULT_HEIGHT,
} = require('./record-replay-session-to-video-puppeteer')

describe('record-replay-session-to-video-puppeteer', () => {
    describe('constants', () => {
        it('has expected default values', () => {
            expect(HEIGHT_OFFSET).toBe(85)
            expect(PLAYBACK_SPEED_MULTIPLIER).toBe(4)
            expect(MAX_DIMENSION).toBe(1400)
            expect(DEFAULT_WIDTH).toBe(1400)
            expect(DEFAULT_HEIGHT).toBe(600)
        })
    })

    describe('scaleDimensionsIfNeeded', () => {
        it.each([
            // [width, height, maxSize, expectedWidth, expectedHeight, description]
            [800, 600, 1400, 800, 600, 'returns original when both under max'],
            [1400, 600, 1400, 1400, 600, 'returns original when at max'],
            [2800, 600, 1400, 1400, 300, 'scales down when width exceeds max'],
            [600, 2800, 1400, 300, 1400, 'scales down when height exceeds max'],
            [2800, 2100, 1400, 1400, 1050, 'scales by width when width > height'],
            [2100, 2800, 1400, 1050, 1400, 'scales by height when height > width'],
            [2000, 2000, 1400, 1400, 1400, 'scales square dimensions correctly'],
            [100, 100, 1400, 100, 100, 'handles small dimensions'],
            [0, 0, 1400, 0, 0, 'handles zero dimensions'],
        ])('(%d, %d, %d) => (%d, %d) - %s', (width, height, maxSize, expectedWidth, expectedHeight) => {
            const result = scaleDimensionsIfNeeded(width, height, maxSize)
            expect(result).toEqual({ width: expectedWidth, height: expectedHeight })
        })

        it('uses MAX_DIMENSION as default maxSize', () => {
            const result = scaleDimensionsIfNeeded(2800, 600)
            expect(result).toEqual({ width: 1400, height: 300 })
        })
    })

    describe('ensurePlaybackSpeed', () => {
        it.each([
            ['https://example.com/replay', 1, 'https://example.com/replay?playerSpeed=1'],
            ['https://example.com/replay', 4, 'https://example.com/replay?playerSpeed=4'],
            ['https://example.com/replay?foo=bar', 2, 'https://example.com/replay?foo=bar&playerSpeed=2'],
            ['https://example.com/replay?playerSpeed=1', 4, 'https://example.com/replay?playerSpeed=4'],
            ['https://example.com/replay#hash', 3, 'https://example.com/replay?playerSpeed=3#hash'],
        ])('ensurePlaybackSpeed(%s, %d) => %s', (url, speed, expected) => {
            expect(ensurePlaybackSpeed(url, speed)).toBe(expected)
        })

        it('handles float playback speeds', () => {
            const result = ensurePlaybackSpeed('https://example.com/replay', 1.5)
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

        it('continues when navigation times out', async () => {
            mockPage.goto.mockRejectedValue(new Error('Navigation timeout'))

            await expect(
                waitForPageReady(mockPage, 'https://example.com', '.replayer-wrapper')
            ).resolves.toBeUndefined()
            expect(mockPage.waitForSelector).toHaveBeenCalled()
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

    describe('detectRecordingResolution', () => {
        let mockBrowser: { newPage: jest.Mock }
        let mockPage: {
            setViewport: jest.Mock
            goto: jest.Mock
            waitForSelector: jest.Mock
            evaluate: jest.Mock
            close: jest.Mock
        }

        beforeEach(() => {
            mockPage = {
                setViewport: jest.fn().mockResolvedValue(undefined),
                goto: jest.fn().mockResolvedValue(undefined),
                waitForSelector: jest.fn().mockResolvedValue(undefined),
                evaluate: jest.fn(),
                close: jest.fn().mockResolvedValue(undefined),
            }
            mockBrowser = {
                newPage: jest.fn().mockResolvedValue(mockPage),
            }
        })

        it('returns detected resolution from window.__POSTHOG_RESOLUTION__', async () => {
            mockPage.evaluate.mockResolvedValue({ width: 1920, height: 1080 })

            const result = await detectRecordingResolution(
                mockBrowser,
                'https://example.com',
                '.replayer-wrapper',
                1400,
                600
            )

            expect(result).toEqual({ width: 1920, height: 1080 })
            expect(mockPage.setViewport).toHaveBeenCalledWith({ width: 1400, height: 600 })
            expect(mockPage.close).toHaveBeenCalled()
        })

        it('returns default resolution when detection returns null', async () => {
            mockPage.evaluate.mockResolvedValue(null)

            const result = await detectRecordingResolution(
                mockBrowser,
                'https://example.com',
                '.replayer-wrapper',
                1400,
                600
            )

            expect(result).toEqual({ width: 1400, height: 600 })
        })

        it('returns default resolution when page.evaluate throws', async () => {
            mockPage.evaluate.mockRejectedValue(new Error('Evaluation failed'))

            const result = await detectRecordingResolution(
                mockBrowser,
                'https://example.com',
                '.replayer-wrapper',
                1400,
                600
            )

            expect(result).toEqual({ width: 1400, height: 600 })
            expect(mockPage.close).toHaveBeenCalled()
        })

        it('closes page even when detection fails', async () => {
            mockPage.evaluate.mockRejectedValue(new Error('Evaluation failed'))

            await detectRecordingResolution(mockBrowser, 'https://example.com', '.replayer-wrapper', 1400, 600)

            expect(mockPage.close).toHaveBeenCalled()
        })
    })

    describe('waitForRecordingWithSegments', () => {
        let mockPage: { evaluate: jest.Mock }

        beforeEach(() => {
            mockPage = {
                evaluate: jest.fn(),
            }
            jest.useFakeTimers()
        })

        afterEach(() => {
            jest.useRealTimers()
        })

        it('returns empty segments when recording ends immediately', async () => {
            mockPage.evaluate.mockResolvedValue({ ended: true })

            const promise = waitForRecordingWithSegments(mockPage, 5000, Date.now())
            await jest.advanceTimersByTimeAsync(100)
            const result = await promise

            expect(result).toEqual({})
        })

        it('tracks segment changes during recording', async () => {
            const startTime = Date.now()
            let callCount = 0

            mockPage.evaluate.mockImplementation(() => {
                callCount++
                if (callCount === 1) {
                    return Promise.resolve({ counter: 1, segment_start_ts: 0 })
                }
                if (callCount === 2) {
                    return Promise.resolve({ counter: 2, segment_start_ts: 10 })
                }
                return Promise.resolve({ ended: true })
            })

            const promise = waitForRecordingWithSegments(mockPage, 10000, startTime)

            // Advance through the polling cycles
            await jest.advanceTimersByTimeAsync(100)
            await jest.advanceTimersByTimeAsync(100)
            await jest.advanceTimersByTimeAsync(100)

            const result = await promise

            expect(Object.keys(result).length).toBeGreaterThanOrEqual(1)
        })

        it('stops when maxWaitMs is reached', async () => {
            mockPage.evaluate.mockResolvedValue(null) // No segment changes, no end signal

            const startTime = Date.now()
            const promise = waitForRecordingWithSegments(mockPage, 1000, startTime)

            // Advance past maxWaitMs
            await jest.advanceTimersByTimeAsync(1100)

            const result = await promise
            expect(result).toEqual({})
        })

        it('continues polling when evaluate returns null', async () => {
            let callCount = 0
            mockPage.evaluate.mockImplementation(() => {
                callCount++
                if (callCount < 3) {
                    return Promise.resolve(null)
                }
                return Promise.resolve({ ended: true })
            })

            const promise = waitForRecordingWithSegments(mockPage, 10000, Date.now())

            await jest.advanceTimersByTimeAsync(3000)

            await promise

            expect(callCount).toBeGreaterThanOrEqual(3)
        })

        it('handles evaluate errors gracefully', async () => {
            let callCount = 0
            mockPage.evaluate.mockImplementation(() => {
                callCount++
                if (callCount === 1) {
                    return Promise.reject(new Error('Evaluation error'))
                }
                return Promise.resolve({ ended: true })
            })

            const promise = waitForRecordingWithSegments(mockPage, 10000, Date.now())

            await jest.advanceTimersByTimeAsync(200)

            const result = await promise
            expect(result).toEqual({})
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
            // The transformation to null happens inside page.evaluate, so mock returns already-transformed data
            mockPage.evaluate.mockResolvedValue([{ ts_from_s: 0, ts_to_s: null, active: true }])

            const result = await detectInactivityPeriods(mockPage, 1, {})

            expect(result).toEqual([{ ts_from_s: 0, ts_to_s: null, active: true }])
        })

        it('merges segment timestamps into periods', async () => {
            mockPage.evaluate.mockResolvedValue([
                { ts_from_s: 0, ts_to_s: 5, active: true },
                { ts_from_s: 10, ts_to_s: 15, active: false },
            ])

            const segmentStartTimestamps = { 0: 1.5, 10: 3.0 }

            const result = await detectInactivityPeriods(mockPage, 2, segmentStartTimestamps)

            expect(result).toEqual([
                { ts_from_s: 0, ts_to_s: 5, active: true, recording_ts_from_s: 3 }, // 1.5 * 2 = 3
                { ts_from_s: 10, ts_to_s: 15, active: false, recording_ts_from_s: 6 }, // 3.0 * 2 = 6
            ])
        })

        it('applies playback speed multiplier to recording timestamps', async () => {
            mockPage.evaluate.mockResolvedValue([{ ts_from_s: 5, ts_to_s: 10, active: false }])

            const segmentStartTimestamps = { 5: 2.5 }

            const result = await detectInactivityPeriods(mockPage, 4, segmentStartTimestamps)

            expect(result[0].recording_ts_from_s).toBe(10) // 2.5 * 4 = 10
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

            const segmentStartTimestamps = { 0: 1.5 } // Only has timestamp for first period

            const result = await detectInactivityPeriods(mockPage, 1, segmentStartTimestamps)

            expect(result[0].recording_ts_from_s).toBe(2) // Math.round(1.5 * 1)
            expect(result[1].recording_ts_from_s).toBeUndefined()
        })
    })
})
