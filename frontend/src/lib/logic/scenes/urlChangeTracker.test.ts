import { getUrlChangeTracker, resetAllTrackers, UrlChangeTracker } from './urlChangeTracker'

describe('getUrlChangeTracker', () => {
    beforeEach(() => {
        jest.useFakeTimers()
        resetAllTrackers()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    it('returns same tracker instance for same logic path', () => {
        const tracker1 = getUrlChangeTracker('webAnalyticsLogic')
        const tracker2 = getUrlChangeTracker('webAnalyticsLogic')

        expect(tracker1).toBe(tracker2)
    })

    it('returns different tracker instances for different logic paths', () => {
        const tracker1 = getUrlChangeTracker('webAnalyticsLogic')
        const tracker2 = getUrlChangeTracker('insightsLogic')

        expect(tracker1).not.toBe(tracker2)
    })

    it('isolates change counts per logic path', () => {
        const webTracker = getUrlChangeTracker('webAnalyticsLogic')
        const insightsTracker = getUrlChangeTracker('insightsLogic')

        for (let i = 0; i < 6; i++) {
            webTracker.recordChange(`/web?v=${i}`, 'webAnalyticsLogic', 'setFilters')
        }

        expect(webTracker.isRapidlyChanging()).toBe(true)
        expect(insightsTracker.isRapidlyChanging()).toBe(false)
    })

    it('resets all trackers with resetAllTrackers', () => {
        const tracker1 = getUrlChangeTracker('webAnalyticsLogic')
        tracker1.recordChange('/web?v=1', 'webAnalyticsLogic', 'setFilters')

        resetAllTrackers()

        const tracker2 = getUrlChangeTracker('webAnalyticsLogic')
        expect(tracker1).not.toBe(tracker2)
        expect(tracker2.getRecentChanges()).toHaveLength(0)
    })
})

describe('UrlChangeTracker', () => {
    let tracker: UrlChangeTracker

    beforeEach(() => {
        jest.useFakeTimers()
        tracker = new UrlChangeTracker()
    })

    afterEach(() => {
        jest.useRealTimers()
    })

    describe('recordChange', () => {
        it('tracks URL changes within the time window', () => {
            tracker.recordChange('/web?foo=bar', 'webAnalyticsLogic', 'setFilters')
            tracker.recordChange('/web?foo=baz', 'webAnalyticsLogic', 'setFilters')

            expect(tracker.getRecentChanges()).toHaveLength(2)
        })

        it('cleans up old entries outside the time window', () => {
            tracker.recordChange('/web?v=1', 'webAnalyticsLogic', 'setFilters')

            jest.advanceTimersByTime(1500) // Beyond default 1000ms window

            tracker.recordChange('/web?v=2', 'webAnalyticsLogic', 'setFilters')

            expect(tracker.getRecentChanges()).toHaveLength(1)
            expect(tracker.getRecentChanges()[0].url).toBe('/web?v=2')
        })

        it('preserves entries within the time window', () => {
            tracker.recordChange('/web?v=1', 'webAnalyticsLogic', 'setFilters')

            jest.advanceTimersByTime(500) // Within default 1000ms window

            tracker.recordChange('/web?v=2', 'webAnalyticsLogic', 'setFilters')

            expect(tracker.getRecentChanges()).toHaveLength(2)
        })
    })

    describe('isRapidlyChanging', () => {
        it.each([
            { count: 3, expected: false },
            { count: 5, expected: false },
            { count: 6, expected: true },
            { count: 10, expected: true },
        ])('returns $expected when $count changes recorded', ({ count, expected }) => {
            for (let i = 0; i < count; i++) {
                tracker.recordChange(`/web?v=${i}`, 'webAnalyticsLogic', 'setFilters')
            }

            expect(tracker.isRapidlyChanging()).toBe(expected)
        })
    })

    describe('warning throttle', () => {
        it('allows first warning', () => {
            expect(tracker.canWarn()).toBe(true)
        })

        it('throttles subsequent warnings within the throttle window', () => {
            tracker.recordWarn()
            expect(tracker.canWarn()).toBe(false)
        })

        it('allows warning after throttle period expires', () => {
            tracker.recordWarn()

            jest.advanceTimersByTime(61000) // Beyond default 60000ms throttle

            expect(tracker.canWarn()).toBe(true)
        })

        it('throttles multiple rapid warning attempts', () => {
            expect(tracker.canWarn()).toBe(true)
            tracker.recordWarn()
            expect(tracker.canWarn()).toBe(false)
            expect(tracker.canWarn()).toBe(false)

            jest.advanceTimersByTime(30000) // Half the throttle period
            expect(tracker.canWarn()).toBe(false)

            jest.advanceTimersByTime(31000) // Beyond the throttle period
            expect(tracker.canWarn()).toBe(true)
        })

        it('canWarn is a pure predicate without side effects', () => {
            expect(tracker.canWarn()).toBe(true)
            expect(tracker.canWarn()).toBe(true)
            expect(tracker.canWarn()).toBe(true)
        })
    })

    describe('getDebugInfo', () => {
        it('returns correct debug information', () => {
            tracker.recordChange('/web?v=1', 'webAnalyticsLogic', 'setFilters')
            tracker.recordChange('/web?v=2', 'webAnalyticsLogic', 'setDates')

            const info = tracker.getDebugInfo()

            expect(info.changeCount).toBe(2)
            expect(info.windowMs).toBe(1000)
            expect(info.recentUrls).toHaveLength(2)
        })

        it('truncates long URLs in debug info', () => {
            const longUrl = '/web?' + 'x'.repeat(300)
            tracker.recordChange(longUrl, 'webAnalyticsLogic', 'setFilters')

            const info = tracker.getDebugInfo()
            const recentUrls = info.recentUrls as Array<{ url: string }>

            expect(recentUrls[0].url.length).toBeLessThanOrEqual(200)
        })

        it('limits recent URLs to last 5', () => {
            for (let i = 0; i < 8; i++) {
                tracker.recordChange(`/web?v=${i}`, 'webAnalyticsLogic', 'setFilters')
            }

            const info = tracker.getDebugInfo()
            const recentUrls = info.recentUrls as Array<{ url: string }>

            expect(recentUrls).toHaveLength(5)
            expect(recentUrls[0].url).toBe('/web?v=3')
            expect(recentUrls[4].url).toBe('/web?v=7')
        })
    })

    describe('reset', () => {
        it('clears all internal state', () => {
            for (let i = 0; i < 10; i++) {
                tracker.recordChange(`/web?v=${i}`, 'webAnalyticsLogic', 'setFilters')
            }
            tracker.recordWarn()

            tracker.reset()

            expect(tracker.getRecentChanges()).toHaveLength(0)
            expect(tracker.canWarn()).toBe(true)
        })
    })

    describe('custom configuration', () => {
        it('respects custom maxChangesPerSecond', () => {
            const customTracker = new UrlChangeTracker({
                maxChangesPerSecond: 2,
            })

            customTracker.recordChange('/web?v=1', 'webAnalyticsLogic', 'setFilters')
            customTracker.recordChange('/web?v=2', 'webAnalyticsLogic', 'setFilters')
            expect(customTracker.isRapidlyChanging()).toBe(false)

            customTracker.recordChange('/web?v=3', 'webAnalyticsLogic', 'setFilters')
            expect(customTracker.isRapidlyChanging()).toBe(true)
        })

        it('respects custom windowMs', () => {
            const customTracker = new UrlChangeTracker({
                windowMs: 500,
            })

            customTracker.recordChange('/web?v=1', 'webAnalyticsLogic', 'setFilters')

            jest.advanceTimersByTime(600)

            customTracker.recordChange('/web?v=2', 'webAnalyticsLogic', 'setFilters')

            expect(customTracker.getRecentChanges()).toHaveLength(1)
        })

        it('respects custom throttleWarningMs', () => {
            const customTracker = new UrlChangeTracker({
                throttleWarningMs: 5000,
            })

            expect(customTracker.canWarn()).toBe(true)
            customTracker.recordWarn()
            expect(customTracker.canWarn()).toBe(false)

            jest.advanceTimersByTime(5001)

            expect(customTracker.canWarn()).toBe(true)
        })
    })
})
