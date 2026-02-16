import { DateTime } from 'luxon'

import { createTestEventHeaders } from '../../../tests/helpers/event-headers'
import { compareTimestamps } from './timestamp-comparison'

describe('compareTimestamps', () => {
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
        const headers = createTestEventHeaders({
            timestamp: '1672574400000', // 2023-01-01T12:00:00Z
        })

        expect(() => {
            compareTimestamps(undefined, headers, 123, 'test-uuid', 'test-context')
        }).not.toThrow()
    })

    it('should handle missing timestamp header without throwing', () => {
        const headers = createTestEventHeaders({
            token: 'test-token',
            distinct_id: 'test-id',
            // timestamp is missing
        })

        expect(() => {
            compareTimestamps('2023-01-01T12:00:00Z', headers, 123, 'test-uuid', 'test-context')
        }).not.toThrow()
    })

    it('should handle invalid timestamp header without throwing', () => {
        const headers = createTestEventHeaders({
            timestamp: 'not-a-number',
        })

        expect(() => {
            compareTimestamps('2023-01-01T12:00:00Z', headers, 123, 'test-uuid', 'test-context')
        }).not.toThrow()
    })

    it('should handle exact match without throwing', () => {
        const timestamp = '2023-01-01T12:00:00Z'
        const timestampMs = DateTime.fromISO(timestamp).toMillis()
        const headers = createTestEventHeaders({
            timestamp: timestampMs.toString(),
        })

        expect(() => {
            compareTimestamps(timestamp, headers, 123, 'test-uuid', 'test-context')
        }).not.toThrow()
    })

    it('should handle timestamp difference without throwing', () => {
        const timestamp = '2023-01-01T12:00:00Z'
        const timestampMs = DateTime.fromISO(timestamp).toMillis()
        const differentTimestampMs = timestampMs + 5000 // 5 seconds difference
        const headers = createTestEventHeaders({
            timestamp: differentTimestampMs.toString(),
        })

        expect(() => {
            compareTimestamps(timestamp, headers, 123, 'test-uuid', 'test-context')
        }).not.toThrow()
    })

    it('should use default context when not provided', () => {
        const headers = createTestEventHeaders({
            timestamp: '1672574400000', // 2023-01-01T12:00:00Z
        })

        expect(() => {
            compareTimestamps('2023-01-01T12:00:00Z', headers, 123, 'test-uuid')
        }).not.toThrow()
    })

    it('should work with different timestamp formats', () => {
        // Test with RFC2822 format - the function should handle it via parseDate
        const timestamp = 'Sun, 01 Jan 2023 12:00:00 GMT'
        const timestampMs = DateTime.fromRFC2822(timestamp).toMillis()
        const headers = createTestEventHeaders({
            timestamp: timestampMs.toString(),
        })

        expect(() => {
            compareTimestamps(timestamp, headers, 123, 'test-uuid', 'test-context')
        }).not.toThrow()
    })

    it('should work without optional parameters', () => {
        const headers = createTestEventHeaders({
            timestamp: '1672574400000',
        })

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
            const headers = createTestEventHeaders({ timestamp: header })

            expect(() => {
                compareTimestamps(timestamp, headers, 123, 'test-uuid', 'test-context')
            }).not.toThrow()
        })
    })
})
