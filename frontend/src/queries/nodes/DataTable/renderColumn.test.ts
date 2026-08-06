import { isEpochTimestamp } from './renderColumn'

describe('renderColumn', () => {
    describe('isEpochTimestamp', () => {
        // The serialized epoch carries the project timezone offset, so a naive "1970-01-01" string
        // match misses it. These cases lock in the millisecond comparison and guard against real
        // dates or non-date values being mistaken for a missing timestamp.
        test.each([
            ['1970-01-01T00:00:00.000Z', true],
            ['1970-01-01T00:00:00Z', true],
            ['1969-12-31T16:00:00-08:00', true], // US/Pacific serialization of epoch 0
            ['1970-01-01T01:00:00+01:00', true],
            ['2026-08-06T12:00:00.000Z', false],
            ['1970-01-01T00:00:01.000Z', false], // one second past the epoch is a real date
            ['0', false],
            ['not a date', false],
            ['', false],
        ])('isEpochTimestamp(%p) === %p', (value, expected) => {
            expect(isEpochTimestamp(value)).toBe(expected)
        })
    })
})
