import { DateTime } from 'luxon'

import { EventHeaders } from '../../types'
import { compareTimestamps } from './timestamp-comparison'

// Mock the logger
const mockLoggerInfo = jest.fn()
const mockLoggerWarn = jest.fn()

jest.mock('../../utils/logger', () => ({
    logger: {
        info: mockLoggerInfo,
        warn: mockLoggerWarn,
    },
}))

// Mock prom-client
const mockLabels = jest.fn().mockReturnThis()
const mockInc = jest.fn()

jest.mock('prom-client', () => ({
    Counter: jest.fn(() => ({
        labels: mockLabels,
        inc: mockInc,
    })),
}))

describe('compareTimestamps', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })

    it('should handle missing headers without throwing', () => {
        expect(() => {
            compareTimestamps('2023-01-01T12:00:00Z', undefined, 123, 'test-uuid', 'test-context')
        }).not.toThrow()

        expect(mockLabels).toHaveBeenCalled()
        expect(mockInc).toHaveBeenCalled()
    })

    it('should handle missing timestamp header without throwing', () => {
        const headers: EventHeaders = {
            token: 'test-token',
            distinct_id: 'test-id',
            // timestamp is missing
        }

        expect(() => {
            compareTimestamps('2023-01-01T12:00:00Z', headers, 123, 'test-uuid', 'test-context')
        }).not.toThrow()

        expect(mockLabels).toHaveBeenCalled()
        expect(mockInc).toHaveBeenCalled()
    })

    it('should handle invalid timestamp header without throwing', () => {
        const headers: EventHeaders = {
            timestamp: 'not-a-number',
        }

        expect(() => {
            compareTimestamps('2023-01-01T12:00:00Z', headers, 123, 'test-uuid', 'test-context')
        }).not.toThrow()

        expect(mockLabels).toHaveBeenCalled()
        expect(mockInc).toHaveBeenCalled()
    })

    it('should handle exact match without throwing', () => {
        const timestamp = '2023-01-01T12:00:00Z'
        const timestampMs = DateTime.fromISO(timestamp).toMillis()
        const headers: EventHeaders = {
            timestamp: timestampMs.toString(),
        }

        expect(() => {
            compareTimestamps(timestamp, headers, 123, 'test-uuid', 'test-context')
        }).not.toThrow()

        expect(mockLabels).toHaveBeenCalled()
        expect(mockInc).toHaveBeenCalled()
    })

    it('should detect timestamp difference and log it', () => {
        const timestamp = '2023-01-01T12:00:00Z'
        const timestampMs = DateTime.fromISO(timestamp).toMillis()
        const differentTimestampMs = timestampMs + 5000 // 5 seconds difference
        const headers: EventHeaders = {
            timestamp: differentTimestampMs.toString(),
        }

        expect(() => {
            compareTimestamps(timestamp, headers, 123, 'test-uuid', 'test-context')
        }).not.toThrow()

        expect(mockLabels).toHaveBeenCalled()
        expect(mockInc).toHaveBeenCalled()
        expect(mockLoggerInfo).toHaveBeenCalledWith(
            'Timestamp difference detected',
            expect.objectContaining({
                context: 'test-context',
                team_id: 123,
                event_uuid: 'test-uuid',
            })
        )
    })

    it('should use default context when not provided', () => {
        const headers: EventHeaders = {
            timestamp: '1672574400000', // 2023-01-01T12:00:00Z
        }

        expect(() => {
            compareTimestamps('2023-01-01T12:00:00Z', headers, 123, 'test-uuid')
        }).not.toThrow()

        expect(mockLabels).toHaveBeenCalled()
        expect(mockInc).toHaveBeenCalled()
    })

    it('should work with different timestamp formats', () => {
        // Test with RFC2822 format - the function should handle it via parseDate
        const timestamp = 'Sun, 01 Jan 2023 12:00:00 GMT'
        const timestampMs = DateTime.fromRFC2822(timestamp).toMillis()
        const headers: EventHeaders = {
            timestamp: timestampMs.toString(),
        }

        expect(() => {
            compareTimestamps(timestamp, headers, 123, 'test-uuid', 'test-context')
        }).not.toThrow()

        expect(mockLabels).toHaveBeenCalled()
        expect(mockInc).toHaveBeenCalled()
    })

    it('should work without optional parameters', () => {
        const headers: EventHeaders = {
            timestamp: '1672574400000',
        }

        expect(() => {
            compareTimestamps('2023-01-01T12:00:00Z', headers, 123)
        }).not.toThrow()

        expect(mockLabels).toHaveBeenCalled()
        expect(mockInc).toHaveBeenCalled()
    })

    it('should handle edge cases gracefully', () => {
        const testCases = [
            { timestamp: '1970-01-01T00:00:00Z', header: '0' }, // Zero timestamp
            {
                timestamp: '2023-01-01T12:00:00.123Z',
                header: DateTime.fromISO('2023-01-01T12:00:00.123Z').toMillis().toString(),
            }, // With milliseconds
            {
                timestamp: '2099-12-31T23:59:59Z',
                header: DateTime.fromISO('2099-12-31T23:59:59Z').toMillis().toString(),
            }, // Future date
        ]

        testCases.forEach(({ timestamp, header }) => {
            const headers: EventHeaders = { timestamp: header }

            expect(() => {
                compareTimestamps(timestamp, headers, 123, 'test-uuid', 'test-context')
            }).not.toThrow()
        })

        expect(mockLabels).toHaveBeenCalled()
        expect(mockInc).toHaveBeenCalled()
    })
})
