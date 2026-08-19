import { ForecastTargetDirection } from '~/queries/schema/schema-general'

import { findFirstCrossing, targetSummary } from './forecastPreviewUtils'

describe('findFirstCrossing', () => {
    const series = (yhat: number[], lower: number[], upper: number[]) => ({ yhat, lower, upper })

    // Mirrors TestFutureBreachSensitivity in the backend. best_case reads the edge that keeps the
    // metric on the acceptable side: the LOWER edge against a ceiling, the UPPER edge against a floor.
    it.each([
        ['forecast crosses a ceiling', false, { upper: 100 }, [95, 105], [70, 80], [120, 130], 1],
        ['forecast clears a ceiling', false, { upper: 100 }, [95, 96], [70, 80], [120, 130], null],
        [
            'best case clears a ceiling the forecast crosses',
            true,
            { upper: 100 },
            [95, 105],
            [70, 80],
            [120, 130],
            null,
        ],
        ['best case crosses a ceiling', true, { upper: 100 }, [150, 160], [110, 120], [180, 190], 0],
        ['forecast crosses a floor', false, { lower: 50 }, [60, 40], [30, 20], [80, 70], 1],
        ['best case clears a floor the forecast crosses', true, { lower: 50 }, [60, 40], [30, 20], [80, 70], null],
        ['best case crosses a floor', true, { lower: 50 }, [20, 10], [5, 2], [30, 40], 0],
    ] as const)('%s', (_n, bestCase, bounds, yhat, lower, upper, expected) => {
        expect(findFirstCrossing(series([...yhat], [...lower], [...upper]), bounds, bestCase)).toBe(expected)
    })

    it('is null without bounds', () => {
        expect(findFirstCrossing(series([1], [0], [2]), null, false)).toBeNull()
    })
})

describe('targetSummary', () => {
    // The two booleans are the two crossings the backend already computed. Rendering both is what
    // lets a user pick a sensitivity by seeing the gap rather than reasoning about credible intervals.
    it.each([
        ['misses both ways', true, true, 'Falls short, and misses even in the best case'],
        ['misses on the forecast only', true, false, 'Falls short on the current forecast'],
        ['on track', false, false, 'On track to reach the target'],
    ])('%s', (_name, missesOnForecast, missesOnBestCase, expected) => {
        expect(
            targetSummary(
                { misses_on_forecast: missesOnForecast, misses_on_best_case: missesOnBestCase },
                ForecastTargetDirection.AT_LEAST
            )
        ).toBe(expected)
    })
    it('reads as an overshoot for an at-most target', () => {
        expect(
            targetSummary({ misses_on_forecast: true, misses_on_best_case: false }, ForecastTargetDirection.AT_MOST)
        ).toBe('Goes over on the current forecast')
    })
})
