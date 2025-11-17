import { logger } from '../../../utils/logger'
import { TopTracker } from './top-tracker'

jest.mock('../../../utils/logger')

describe('TopTracker', () => {
    let tracker: TopTracker
    let mockLoggerInfo: jest.SpyInstance

    beforeEach(() => {
        tracker = new TopTracker()
        mockLoggerInfo = jest.spyOn(logger, 'info').mockImplementation()
    })

    afterEach(() => {
        jest.clearAllMocks()
    })

    describe('increment', () => {
        it('should increment counter for a metric and key', () => {
            tracker.increment('session_size', 'session-123')

            expect(tracker.getCount('session_size', 'session-123')).toBe(1)
        })

        it('should increment by custom count', () => {
            tracker.increment('session_size', 'session-123', 500)

            expect(tracker.getCount('session_size', 'session-123')).toBe(500)
        })

        it('should accumulate counts for same metric and key', () => {
            tracker.increment('session_size', 'session-123', 100)
            tracker.increment('session_size', 'session-123', 200)
            tracker.increment('session_size', 'session-123', 300)

            expect(tracker.getCount('session_size', 'session-123')).toBe(600)
        })

        it('should track different keys for same metric separately', () => {
            tracker.increment('session_size', 'session-123', 100)
            tracker.increment('session_size', 'session-456', 200)

            expect(tracker.getCount('session_size', 'session-123')).toBe(100)
            expect(tracker.getCount('session_size', 'session-456')).toBe(200)
        })

        it('should track different metrics separately', () => {
            tracker.increment('session_size', 'session-123', 100)
            tracker.increment('message_count', 'session-123', 50)

            expect(tracker.getCount('session_size', 'session-123')).toBe(100)
            expect(tracker.getCount('message_count', 'session-123')).toBe(50)
        })
    })

    describe('getCount', () => {
        it('should return 0 for non-existent metric', () => {
            expect(tracker.getCount('non_existent', 'key-123')).toBe(0)
        })

        it('should return 0 for non-existent key', () => {
            tracker.increment('session_size', 'session-123', 100)

            expect(tracker.getCount('session_size', 'non-existent')).toBe(0)
        })
    })

    describe('getMetrics', () => {
        it('should return empty array when no metrics tracked', () => {
            expect(tracker.getMetrics()).toEqual([])
        })

        it('should return all tracked metrics', () => {
            tracker.increment('session_size', 'session-123')
            tracker.increment('message_count', 'session-456')
            tracker.increment('event_count', 'session-789')

            const metrics = tracker.getMetrics()
            expect(metrics).toHaveLength(3)
            expect(metrics).toContain('session_size')
            expect(metrics).toContain('message_count')
            expect(metrics).toContain('event_count')
        })
    })

    describe('logAndReset', () => {
        it('should log top N entries sorted by count descending', () => {
            tracker.increment('session_size', 'session-1', 100)
            tracker.increment('session_size', 'session-2', 500)
            tracker.increment('session_size', 'session-3', 300)
            tracker.increment('session_size', 'session-4', 200)

            tracker.logAndReset(3)

            expect(mockLoggerInfo).toHaveBeenCalledWith('📊 Top entries for metric', {
                metric: 'session_size',
                topN: 3,
                entries: [
                    { key: 'session-2', count: 500 },
                    { key: 'session-3', count: 300 },
                    { key: 'session-4', count: 200 },
                ],
                totalKeys: 4,
            })
        })

        it('should log all entries when topN is greater than total entries', () => {
            tracker.increment('session_size', 'session-1', 100)
            tracker.increment('session_size', 'session-2', 200)

            tracker.logAndReset(10)

            expect(mockLoggerInfo).toHaveBeenCalledWith('📊 Top entries for metric', {
                metric: 'session_size',
                topN: 10,
                entries: [
                    { key: 'session-2', count: 200 },
                    { key: 'session-1', count: 100 },
                ],
                totalKeys: 2,
            })
        })

        it('should log multiple metrics separately', () => {
            tracker.increment('session_size', 'session-1', 1000)
            tracker.increment('session_size', 'session-2', 2000)
            tracker.increment('message_count', 'session-1', 50)
            tracker.increment('message_count', 'session-2', 100)

            tracker.logAndReset(2)

            expect(mockLoggerInfo).toHaveBeenCalledTimes(2)
            expect(mockLoggerInfo).toHaveBeenCalledWith('📊 Top entries for metric', {
                metric: 'session_size',
                topN: 2,
                entries: [
                    { key: 'session-2', count: 2000 },
                    { key: 'session-1', count: 1000 },
                ],
                totalKeys: 2,
            })
            expect(mockLoggerInfo).toHaveBeenCalledWith('📊 Top entries for metric', {
                metric: 'message_count',
                topN: 2,
                entries: [
                    { key: 'session-2', count: 100 },
                    { key: 'session-1', count: 50 },
                ],
                totalKeys: 2,
            })
        })

        it('should reset all counters after logging', () => {
            tracker.increment('session_size', 'session-1', 100)
            tracker.increment('message_count', 'session-2', 50)

            tracker.logAndReset(5)

            expect(tracker.getCount('session_size', 'session-1')).toBe(0)
            expect(tracker.getCount('message_count', 'session-2')).toBe(0)
            expect(tracker.getMetrics()).toEqual([])
        })

        it('should not log metrics with no entries', () => {
            tracker.logAndReset(5)

            expect(mockLoggerInfo).not.toHaveBeenCalled()
        })

        it('should handle single entry', () => {
            tracker.increment('session_size', 'session-1', 100)

            tracker.logAndReset(1)

            expect(mockLoggerInfo).toHaveBeenCalledWith('📊 Top entries for metric', {
                metric: 'session_size',
                topN: 1,
                entries: [{ key: 'session-1', count: 100 }],
                totalKeys: 1,
            })
        })

        it('should handle topN of 0', () => {
            tracker.increment('session_size', 'session-1', 100)
            tracker.increment('session_size', 'session-2', 200)

            tracker.logAndReset(0)

            expect(mockLoggerInfo).toHaveBeenCalledWith('📊 Top entries for metric', {
                metric: 'session_size',
                topN: 0,
                entries: [],
                totalKeys: 2,
            })
        })
    })

    describe('integration scenarios', () => {
        it('should track session sizes and log top sessions', () => {
            // Simulate tracking session sizes
            tracker.increment('session_size', 'session-abc', 1024)
            tracker.increment('session_size', 'session-def', 2048)
            tracker.increment('session_size', 'session-abc', 512) // Same session, more data
            tracker.increment('session_size', 'session-ghi', 4096)

            tracker.logAndReset(2)

            expect(mockLoggerInfo).toHaveBeenCalledWith('📊 Top entries for metric', {
                metric: 'session_size',
                topN: 2,
                entries: [
                    { key: 'session-ghi', count: 4096 },
                    { key: 'session-def', count: 2048 },
                ],
                totalKeys: 3,
            })
        })

        it('should allow reuse after reset', () => {
            tracker.increment('session_size', 'session-1', 100)
            tracker.logAndReset(5)

            tracker.increment('session_size', 'session-2', 200)
            tracker.logAndReset(5)

            expect(mockLoggerInfo).toHaveBeenCalledTimes(2)
            expect(mockLoggerInfo).toHaveBeenLastCalledWith('📊 Top entries for metric', {
                metric: 'session_size',
                topN: 5,
                entries: [{ key: 'session-2', count: 200 }],
                totalKeys: 1,
            })
        })
    })
})
