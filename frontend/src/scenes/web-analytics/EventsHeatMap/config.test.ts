import { DaysAbbreviated, HoursAbbreviated, Sum } from './config'

describe('EventsHeatMap config', () => {
    describe('Sum aggregation', () => {
        it('should sum an array of numbers correctly', () => {
            expect(Sum.fn([1, 2, 3, 4])).toBe(10)
            expect(Sum.fn([])).toBe(0)
            expect(Sum.fn([0, -1, 1])).toBe(0)
        })
    })

    describe('DaysAbbreviated', () => {
        it('should have correct days configuration', () => {
            // we care about the order of the days and the startIndex
            expect(DaysAbbreviated.values).toEqual(['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'])
            expect(DaysAbbreviated.startIndex).toBe(0)
        })

        it('should have 7 days', () => {
            expect(DaysAbbreviated.values.length).toBe(7)
        })
    })

    describe('HoursAbbreviated', () => {
        it('should have correct hours configuration', () => {
            // we care about the order of the hours and the startIndex
            const expectedHours = Array.from({ length: 24 }, (_, i) => String(i))
            expect(HoursAbbreviated.values).toEqual(expectedHours)
            expect(HoursAbbreviated.startIndex).toBe(0)
        })

        it('should have 24 hours', () => {
            // make sure we have 24 hours
            expect(HoursAbbreviated.values.length).toBe(24)
        })
    })
})
