import type { ProcessedTimeseriesDataPoint } from '../../experimentTimeseriesLogic'
import { DELTA_SERIES_KEY, buildVariantTimeseriesSeries } from './variantTimeseriesTransforms'

const VARIANT_COLOR = '#1d4aff'

function points(hasRealData: boolean[]): ProcessedTimeseriesDataPoint[] {
    return hasRealData.map((real, i) => ({
        date: `2026-06-0${i + 1}`,
        value: 0.01 * (i + 1),
        lower_bound: -0.01 * (i + 1),
        upper_bound: 0.02 * (i + 1),
        hasRealData: real,
    }))
}

describe('buildVariantTimeseriesSeries', () => {
    it('dashes from the first pending day, not from the last measured one', () => {
        const { series } = buildVariantTimeseriesSeries(points([true, true, true, false, false]), VARIANT_COLOR)

        expect(series[0].stroke?.partial?.fromIndex).toBe(3)
    })

    it('leaves the line solid when every day is measured', () => {
        const { series } = buildVariantTimeseriesSeries(points([true, true, true]), VARIANT_COLOR)

        expect(series[0].stroke).toBeUndefined()
    })

    it('dashes the whole line when no day has been measured yet', () => {
        const { series } = buildVariantTimeseriesSeries(points([false, false, false]), VARIANT_COLOR)

        expect(series[0].stroke?.partial?.fromIndex).toBe(0)
    })

    it('keeps the series and both confidence bounds the same length as the input', () => {
        const { series, lowerBounds, upperBounds } = buildVariantTimeseriesSeries(
            points([true, true, false]),
            VARIANT_COLOR
        )

        expect(series[0].key).toBe(DELTA_SERIES_KEY)
        expect(series[0].data).toHaveLength(3)
        expect(lowerBounds).toHaveLength(3)
        expect(upperBounds).toHaveLength(3)
    })

    it('substitutes zero for missing values and bounds', () => {
        const missing: ProcessedTimeseriesDataPoint[] = [
            { date: '2026-06-01', value: null, lower_bound: null, upper_bound: null, hasRealData: true },
        ]

        const { series, lowerBounds, upperBounds } = buildVariantTimeseriesSeries(missing, VARIANT_COLOR)

        expect(series[0].data).toEqual([0])
        expect(lowerBounds).toEqual([0])
        expect(upperBounds).toEqual([0])
    })
})
