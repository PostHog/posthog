import { SampleRatioMismatch } from '~/queries/schema/schema-general'

import { getSrmStatus } from './exposuresTransforms'

describe('getSrmStatus', () => {
    const srm = (p_value: number, daily?: { date: string; p_value: number }): SampleRatioMismatch => ({
        expected: { control: 500, test: 500 },
        p_value,
        daily,
    })

    it.each([
        ['mismatch', 0.0009],
        ['borderline', 0.001],
        ['borderline', 0.049],
        ['healthy', 0.05],
    ])('returns %s for a cumulative p-value of %p', (expected, p_value) => {
        expect(getSrmStatus(srm(p_value as number))).toEqual(expected)
    })

    it('reports drift when the totals look healthy but a single day does not', () => {
        expect(getSrmStatus(srm(0.6, { date: '2025-05-26', p_value: 0.004 }))).toEqual('dailyDrift')
    })

    it('stays healthy when neither the totals nor any day is off', () => {
        expect(getSrmStatus(srm(0.6, { date: '2025-05-26', p_value: 0.7 }))).toEqual('healthy')
    })

    it('keeps the cumulative mismatch when a day is off too', () => {
        expect(getSrmStatus(srm(0.00001, { date: '2025-05-26', p_value: 0.004 }))).toEqual('mismatch')
    })
})
