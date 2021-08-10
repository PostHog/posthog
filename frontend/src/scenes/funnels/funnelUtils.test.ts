import { FunnelConversionWindowTimeUnit } from '~/types'
import { calculateDays, getTimeValue } from 'scenes/funnels/funnelUtils'

describe('getTimeValue()', () => {
    it('returns the correct time value', () => {
        expect(getTimeValue(FunnelConversionWindowTimeUnit.Day, 0)).toEqual(0)
        expect(getTimeValue(FunnelConversionWindowTimeUnit.Day, 7)).toEqual(7)
        expect(getTimeValue(FunnelConversionWindowTimeUnit.Day)).toEqual(14)
        expect(getTimeValue(FunnelConversionWindowTimeUnit.Day, undefined, 7)).toEqual(7)
        expect(getTimeValue(FunnelConversionWindowTimeUnit.Week, 0)).toEqual(0)
        expect(getTimeValue(FunnelConversionWindowTimeUnit.Week, 6)).toEqual(0)
        expect(getTimeValue(FunnelConversionWindowTimeUnit.Week, 7)).toEqual(1)
        expect(getTimeValue(FunnelConversionWindowTimeUnit.Week, 364)).toEqual(52)
        expect(getTimeValue(FunnelConversionWindowTimeUnit.Week, 100)).toEqual(14)
        expect(getTimeValue(FunnelConversionWindowTimeUnit.Week)).toEqual(2)
        expect(getTimeValue(FunnelConversionWindowTimeUnit.Week, undefined, 7)).toEqual(1)
    })
})

describe('calculateDays()', () => {
    it('returns the correct number of days', () => {
        expect(calculateDays(FunnelConversionWindowTimeUnit.Day, 0)).toEqual(0)
        expect(calculateDays(FunnelConversionWindowTimeUnit.Day, 7)).toEqual(0)
        expect(calculateDays(FunnelConversionWindowTimeUnit.Day, -1)).toEqual(0)
        expect(calculateDays(FunnelConversionWindowTimeUnit.Day, 366)).toEqual(0)
        expect(calculateDays(FunnelConversionWindowTimeUnit.Week, 0)).toEqual(0)
        expect(calculateDays(FunnelConversionWindowTimeUnit.Week, 3)).toEqual(21)
        expect(calculateDays(FunnelConversionWindowTimeUnit.Week, -1)).toEqual(0)
        expect(calculateDays(FunnelConversionWindowTimeUnit.Week, 52)).toEqual(364)
        expect(calculateDays(FunnelConversionWindowTimeUnit.Week, 53)).toEqual(365)
    })
})
