import { DaysAbbreviated, HoursAbbreviated } from './utils'

describe('EventsHeatMap config', () => {
    describe('DaysAbbreviated', () => {
        it('should have correct days configuration', () => {
            // we care about the order of the days and the startIndex
            expect(DaysAbbreviated.values).toEqual(['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'])
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
        })

        it('should have 24 hours', () => {
            // make sure we have 24 hours
            expect(HoursAbbreviated.values.length).toBe(24)
        })
    })
})
