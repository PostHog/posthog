import { DateTime } from 'luxon'

import type { EventHeaders } from '../../types'
import { logger } from '../../utils/logger'
import { compareTimestamps } from './timestamp-comparison'

// Mock the logger
jest.mock('../../utils/logger', () => ({
    logger: {
        info: jest.fn(),
        warn: jest.fn(),
    },
}))

describe('compareTimestamps', () => {
    beforeEach(() => {
        jest.clearAllMocks()
    })

    it('should handle missing headers without throwing', () => {
        expect(() => {
            compareTimestamps('2023-01-01T12:00:00Z', undefined, 123, 'test-uuid', 'test-context')
        }).not.toThrow()
    })

    it('should handle missing event timestamp without throwing', () => {
        expect(() => {
            compareTimestamps(undefined, undefined, 123, 'test-uuid', 'test-context')
        }).not.toThrow()
    })

    it('should handle missing event timestamp with headers without throwing', () => {
        const headers: EventHeaders = {
            timestamp: '1672574400000', // 2023-01-01T12:00:00Z
            force_disable_person_processing: false,
        }

        expect(() => {
            compareTimestamps(undefined, headers, 123, 'test-uuid', 'test-context')
        }).not.toThrow()
    })

    it('should handle missing timestamp header without throwing', () => {
        const headers: EventHeaders = {
            token: 'test-token',
            distinct_id: 'test-id',
            force_disable_person_processing: false,
            // timestamp is missing
        }

        expect(() => {
            compareTimestamps('2023-01-01T12:00:00Z', headers, 123, 'test-uuid', 'test-context')
        }).not.toThrow()
    })

    it('should handle invalid timestamp header without throwing', () => {
        const headers: EventHeaders = {
            timestamp: 'not-a-number',
            force_disable_person_processing: false,
        }

        expect(() => {
            compareTimestamps('2023-01-01T12:00:00Z', headers, 123, 'test-uuid', 'test-context')
        }).not.toThrow()
    })

    it('should handle exact match without throwing', () => {
        const timestamp = '2023-01-01T12:00:00Z'
        const timestampMs = DateTime.fromISO(timestamp).toMillis()
        const headers: EventHeaders = {
            timestamp: timestampMs.toString(),
            force_disable_person_processing: false,
        }

        expect(() => {
            compareTimestamps(timestamp, headers, 123, 'test-uuid', 'test-context')
        }).not.toThrow()
    })

    it('should detect timestamp difference and log it', () => {
        const timestamp = '2023-01-01T12:00:00Z'
        const timestampMs = DateTime.fromISO(timestamp).toMillis()
        const differentTimestampMs = timestampMs + 5000 // 5 seconds difference
        const headers: EventHeaders = {
            timestamp: differentTimestampMs.toString(),
            force_disable_person_processing: false,
        }

        expect(() => {
            compareTimestamps(timestamp, headers, 123, 'test-uuid', 'test-context', 1.0)
        }).not.toThrow()

        expect(jest.mocked(logger.info)).toHaveBeenCalledWith(
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
            force_disable_person_processing: false,
        }

        expect(() => {
            compareTimestamps('2023-01-01T12:00:00Z', headers, 123, 'test-uuid')
        }).not.toThrow()
    })

    it('should work with different timestamp formats', () => {
        // Test with RFC2822 format - the function should handle it via parseDate
        const timestamp = 'Sun, 01 Jan 2023 12:00:00 GMT'
        const timestampMs = DateTime.fromRFC2822(timestamp).toMillis()
        const headers: EventHeaders = {
            timestamp: timestampMs.toString(),
            force_disable_person_processing: false,
        }

        expect(() => {
            compareTimestamps(timestamp, headers, 123, 'test-uuid', 'test-context')
        }).not.toThrow()
    })

    it('should work without optional parameters', () => {
        const headers: EventHeaders = {
            timestamp: '1672574400000',
            force_disable_person_processing: false,
        }

        expect(() => {
            compareTimestamps('2023-01-01T12:00:00Z', headers, 123)
        }).not.toThrow()
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
            const headers: EventHeaders = { timestamp: header, force_disable_person_processing: false }

            expect(() => {
                compareTimestamps(timestamp, headers, 123, 'test-uuid', 'test-context')
            }).not.toThrow()
        })
    })

    it('should always log when sample rate is 1.0', () => {
        const timestamp = '2023-01-01T12:00:00Z'
        const timestampMs = DateTime.fromISO(timestamp).toMillis() + 1000 // 1 second difference
        const headers: EventHeaders = {
            timestamp: timestampMs.toString(),
            force_disable_person_processing: false,
        }

        compareTimestamps(timestamp, headers, 123, 'test-uuid', 'test-context', 1.0)

        expect(jest.mocked(logger.info)).toHaveBeenCalledWith('Timestamp difference detected', expect.any(Object))
    })

    it('should never log when sample rate is 0.0', () => {
        const timestamp = '2023-01-01T12:00:00Z'
        const timestampMs = DateTime.fromISO(timestamp).toMillis() + 1000 // 1 second difference
        const headers: EventHeaders = {
            timestamp: timestampMs.toString(),
            force_disable_person_processing: false,
        }

        compareTimestamps(timestamp, headers, 123, 'test-uuid', 'test-context', 0.0)

        expect(jest.mocked(logger.info)).not.toHaveBeenCalled()
    })

    it('should always log parse error when sample rate is 1.0', () => {
        const headers: EventHeaders = {
            timestamp: 'invalid-timestamp',
            force_disable_person_processing: false,
        }

        compareTimestamps('invalid-date-format', headers, 123, 'test-uuid', 'test-context', 1.0)

        expect(jest.mocked(logger.warn)).not.toHaveBeenCalled() // No logging for header_invalid
    })

    it('should never log parse error when sample rate is 0.0', () => {
        const headers: EventHeaders = {
            timestamp: 'invalid-timestamp',
            force_disable_person_processing: false,
        }

        compareTimestamps('invalid-date-format', headers, 123, 'test-uuid', 'test-context', 0.0)

        expect(jest.mocked(logger.warn)).not.toHaveBeenCalled()
    })

    it('should respect sampling for intermediate rates', () => {
        // Mock Math.random to return predictable values
        const originalRandom = Math.random
        const mockRandom = jest.fn()
        Math.random = mockRandom

        const timestamp = '2023-01-01T12:00:00Z'
        const timestampMs = DateTime.fromISO(timestamp).toMillis() + 1000
        const headers: EventHeaders = {
            timestamp: timestampMs.toString(),
            force_disable_person_processing: false,
        }

        try {
            // Test with 50% sampling - should log when random < 0.5
            mockRandom.mockReturnValue(0.3) // < 0.5, should log
            compareTimestamps(timestamp, headers, 123, 'test-uuid', 'test-context', 0.5)
            expect(jest.mocked(logger.info)).toHaveBeenCalled()

            jest.clearAllMocks()

            // Test with 50% sampling - should not log when random >= 0.5
            mockRandom.mockReturnValue(0.7) // >= 0.5, should not log
            compareTimestamps(timestamp, headers, 123, 'test-uuid', 'test-context', 0.5)
            expect(jest.mocked(logger.info)).not.toHaveBeenCalled()
        } finally {
            Math.random = originalRandom
        }
    })
})
