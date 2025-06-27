import { DateTime } from 'luxon'

import { calculatedScheduledAt } from './delay'

describe('calculatedScheduledAt', () => {
    let startedAtTimestamp: number

    beforeEach(() => {
        const fixedTime = new Date('2025-01-01T00:00:00.000Z')
        jest.spyOn(Date, 'now').mockReturnValue(fixedTime.getTime())
        startedAtTimestamp = DateTime.utc().toMillis()
    })

    describe('delay duration parsing', () => {
        it.each([
            ['1d', { days: 1 }],
            ['2h', { hours: 2 }],
            ['30m', { minutes: 30 }],
            ['45s', { seconds: 45 }],
            ['1.5h', { hours: 1.5 }],
        ])('should parse duration %s correctly', (duration, expected) => {
            const result = calculatedScheduledAt(duration, startedAtTimestamp)
            expect(result).toEqual(DateTime.utc().plus(expected))
        })

        it('should throw error for invalid duration format', () => {
            expect(() => calculatedScheduledAt('invalid', startedAtTimestamp)).toThrow('Invalid duration: invalid')
        })

        it('should throw error for invalid duration unit', () => {
            expect(() => calculatedScheduledAt('10x', startedAtTimestamp)).toThrow('Invalid duration: 10x')
        })
    })

    describe('delay timing', () => {
        it.each([
            ['1m', DateTime.fromISO('2025-01-01T00:00:00.000Z').toUTC().plus({ minutes: 1 })],
            ['2h', DateTime.fromISO('2025-01-01T00:00:00.000Z').toUTC().plus({ hours: 2 })],
            ['1d', DateTime.fromISO('2025-01-01T00:00:00.000Z').toUTC().plus({ days: 1 })],
        ])('should schedule for correct time with duration %s', (duration, expectedTime) => {
            const result = calculatedScheduledAt(duration, startedAtTimestamp)
            expect(result).toEqual(expectedTime)
        })

        it('should return null if delay time has already passed', () => {
            // Set start time to 1 hour ago
            const pastTimestamp = DateTime.utc().minus({ hours: 1 }).toMillis()
            const result = calculatedScheduledAt('30m', pastTimestamp)
            expect(result).toBeNull()

            const result2 = calculatedScheduledAt('61m', pastTimestamp)
            expect(result2).toEqual(DateTime.utc().plus({ minutes: 1 }))
        })
    })

    describe('max delay duration', () => {
        it('should use max delay duration if provided and smaller than wait time', () => {
            const result = calculatedScheduledAt('2h', startedAtTimestamp, 300) // 5 minutes max
            expect(result).toEqual(DateTime.utc().plus({ seconds: 300 }))
        })

        it('should use wait time if smaller than max delay duration', () => {
            const result = calculatedScheduledAt('1m', startedAtTimestamp, 300) // 5 minutes max
            expect(result).toEqual(DateTime.utc().plus({ minutes: 1 }))
        })
    })

    describe('error handling', () => {
        it('should throw error if startedAtTimestamp is undefined', () => {
            expect(() => calculatedScheduledAt('1h', undefined)).toThrow(
                "'startedAtTimestamp' is not set or is invalid"
            )
        })

        it('should throw error if startedAtTimestamp is invalid', () => {
            expect(() => calculatedScheduledAt('1h', 0)).toThrow("'startedAtTimestamp' is not set or is invalid")
        })
    })
})
