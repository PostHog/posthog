import {
    calculateDays,
    ceilMsToClosestSecond,
    colonDelimitedDuration,
    floorMsToClosestSecond,
    humanFriendlyDuration,
    reverseColonDelimitedDuration,
} from 'lib/utils/durations'

import { TimeUnitType } from '~/types'

describe('durations utils', () => {
    describe('humanFriendlyDuration()', () => {
        it('returns correct value for 0 <= t < 1', () => {
            expect(humanFriendlyDuration(0)).toEqual('0s')
            expect(humanFriendlyDuration(0.001)).toEqual('1ms')
            expect(humanFriendlyDuration(0.02)).toEqual('20ms')
            expect(humanFriendlyDuration(0.3)).toEqual('300ms')
            expect(humanFriendlyDuration(0.999)).toEqual('999ms')
        })

        it('returns correct value for 1 < t <= 60', () => {
            expect(humanFriendlyDuration(60)).toEqual('1m')
            expect(humanFriendlyDuration(45)).toEqual('45s')
            expect(humanFriendlyDuration(44.8)).toEqual('45s')
            expect(humanFriendlyDuration(45.2)).toEqual('45s')
            expect(humanFriendlyDuration(45.2, { secondsFixed: 1 })).toEqual('45.2s')
            expect(humanFriendlyDuration(1.23)).toEqual('1s')
            expect(humanFriendlyDuration(1.23, { secondsPrecision: 3 })).toEqual('1.23s')
            expect(humanFriendlyDuration(1, { secondsPrecision: 3 })).toEqual('1s')
            expect(humanFriendlyDuration(1, { secondsFixed: 1 })).toEqual('1s')
            expect(humanFriendlyDuration(1)).toEqual('1s')
        })
        it('returns correct value for 60 < t < 120', () => {
            expect(humanFriendlyDuration(119.6)).toEqual('1m 59s')
            expect(humanFriendlyDuration(90)).toEqual('1m 30s')
        })
        it('returns correct value for t > 120', () => {
            expect(humanFriendlyDuration(360)).toEqual('6m')
        })
        it('returns correct value for t >= 3600', () => {
            expect(humanFriendlyDuration(3600)).toEqual('1h')
            expect(humanFriendlyDuration(3601)).toEqual('1h 1s')
            expect(humanFriendlyDuration(3961)).toEqual('1h 6m 1s')
            expect(humanFriendlyDuration(3961.333)).toEqual('1h 6m 1s')
            expect(humanFriendlyDuration(3961.666)).toEqual('1h 6m 1s')
        })
        it('returns correct value for t >= 86400', () => {
            expect(humanFriendlyDuration(86400)).toEqual('1d')
            expect(humanFriendlyDuration(86400.12)).toEqual('1d')
        })
        it('truncates to specified # of units', () => {
            expect(humanFriendlyDuration(3961, { maxUnits: 2 })).toEqual('1h 6m')
            expect(humanFriendlyDuration(30, { maxUnits: 2 })).toEqual('30s') // no change
            expect(humanFriendlyDuration(30, { maxUnits: 0 })).toEqual('') // returns no units (useless)
        })
        it('returns an empty string for nullish inputs', () => {
            expect(humanFriendlyDuration('', { maxUnits: 2 })).toEqual('')
            expect(humanFriendlyDuration(null, { maxUnits: 2 })).toEqual('')
        })
    })

    describe('colonDelimitedDuration()', () => {
        it('returns correct value for <= 60', () => {
            expect(colonDelimitedDuration(59.9)).toEqual('00:00:59')
            expect(colonDelimitedDuration(60)).toEqual('00:01:00')
            expect(colonDelimitedDuration(45)).toEqual('00:00:45')
        })
        it('returns correct value for 60 < t < 120', () => {
            expect(colonDelimitedDuration(90)).toEqual('00:01:30')
        })
        it('returns correct value for t > 120', () => {
            expect(colonDelimitedDuration(360)).toEqual('00:06:00')
            expect(colonDelimitedDuration(360.3233)).toEqual('00:06:00')
            expect(colonDelimitedDuration(360.782)).toEqual('00:06:00')
        })
        it('returns correct value for t >= 3600', () => {
            expect(colonDelimitedDuration(3600)).toEqual('01:00:00')
            expect(colonDelimitedDuration(3601)).toEqual('01:00:01')
            expect(colonDelimitedDuration(3961)).toEqual('01:06:01')
        })
        it('returns correct value for t >= 86400', () => {
            expect(colonDelimitedDuration(86400)).toEqual('24:00:00')
            expect(colonDelimitedDuration(90000)).toEqual('25:00:00')
        })
        it('returns correct value for numUnits < 3', () => {
            expect(colonDelimitedDuration(86400, 2)).toEqual('1440:00')
            expect(colonDelimitedDuration(86400, 1)).toEqual('86400')
        })
        it('returns correct value for numUnits >= 4', () => {
            expect(colonDelimitedDuration(86400, 4)).toEqual('01:00:00:00')
            expect(colonDelimitedDuration(90000, 4)).toEqual('01:01:00:00')
            expect(colonDelimitedDuration(90061, 4)).toEqual('01:01:01:01')
            expect(colonDelimitedDuration(604800, 5)).toEqual('01:00:00:00:00')
            expect(colonDelimitedDuration(604800, 6)).toEqual('01:00:00:00:00')
            expect(colonDelimitedDuration(604800.222, 5)).toEqual('01:00:00:00:00')
            expect(colonDelimitedDuration(604800.999, 6)).toEqual('01:00:00:00:00')
        })
        it('returns the smallest possible for numUnits = null', () => {
            expect(colonDelimitedDuration(59, null)).toEqual('00:59')
            expect(colonDelimitedDuration(3599, null)).toEqual('59:59')
            expect(colonDelimitedDuration(3600, null)).toEqual('01:00:00')
        })
        it('returns an empty string for nullish inputs', () => {
            expect(colonDelimitedDuration('')).toEqual('')
            expect(colonDelimitedDuration(null)).toEqual('')
            expect(colonDelimitedDuration(undefined)).toEqual('')
        })
    })

    describe('reverseColonDelimitedDuration()', () => {
        it('returns correct value', () => {
            expect(reverseColonDelimitedDuration('59')).toEqual(59)
            expect(reverseColonDelimitedDuration('59:59')).toEqual(3599)
            expect(reverseColonDelimitedDuration('23:59:59')).toEqual(86399)
        })
        it('returns an null for bad values', () => {
            expect(reverseColonDelimitedDuration('1232123')).toEqual(null)
            expect(reverseColonDelimitedDuration('AA:AA:AA')).toEqual(null)
            expect(reverseColonDelimitedDuration(undefined)).toEqual(null)
        })
    })

    describe('{floor|ceil}MsToClosestSecond()', () => {
        describe('ceil', () => {
            it('handles ms as expected', () => {
                expect(ceilMsToClosestSecond(10532)).toEqual(11000)
                expect(ceilMsToClosestSecond(1500)).toEqual(2000)
                expect(ceilMsToClosestSecond(500)).toEqual(1000)
                expect(ceilMsToClosestSecond(-10532)).toEqual(-10000)
                expect(ceilMsToClosestSecond(-1500)).toEqual(-1000)
                expect(ceilMsToClosestSecond(-500)).toEqual(-0)
            })
            it('handles whole seconds as expected', () => {
                expect(ceilMsToClosestSecond(0)).toEqual(0)
                expect(ceilMsToClosestSecond(1000)).toEqual(1000)
                expect(ceilMsToClosestSecond(-1000)).toEqual(-1000)
            })
        })

        describe('floor', () => {
            it('handles ms as expected', () => {
                expect(floorMsToClosestSecond(10532)).toEqual(10000)
                expect(floorMsToClosestSecond(1500)).toEqual(1000)
                expect(floorMsToClosestSecond(500)).toEqual(0)
                expect(floorMsToClosestSecond(-10532)).toEqual(-11000)
                expect(floorMsToClosestSecond(-1500)).toEqual(-2000)
                expect(floorMsToClosestSecond(-500)).toEqual(-1000)
            })
            it('handles whole seconds as expected', () => {
                expect(floorMsToClosestSecond(0)).toEqual(0)
                expect(floorMsToClosestSecond(1000)).toEqual(1000)
                expect(floorMsToClosestSecond(-1000)).toEqual(-1000)
            })
        })
    })

    describe('calculateDays', () => {
        it('1 day to 1 day', () => {
            expect(calculateDays(1, TimeUnitType.Day)).toEqual(1)
        })
        it('1 week to 7 days', () => {
            expect(calculateDays(1, TimeUnitType.Week)).toEqual(7)
        })
        it('1 month to 30 days', () => {
            expect(calculateDays(1, TimeUnitType.Month)).toEqual(30)
        })
        it('1 year to 365 days', () => {
            expect(calculateDays(1, TimeUnitType.Year)).toEqual(365)
        })
    })
})
