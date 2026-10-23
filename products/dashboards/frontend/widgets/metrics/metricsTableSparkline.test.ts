import { metricsTableSparklineCoordinates, metricsTableSparklineDomains } from './metricsTableSparkline'

const HEIGHT = 24

describe('metricsTableSparkline', () => {
    it.each([
        ['mixed signs', [[-10, 10]]],
        ['all negative', [[-30, -10, -20]]],
        ['all positive', [[5, 10, 0]]],
    ])('keeps every point inside the chart and spreads the line for %s values', (_name, columnValues) => {
        const [domain] = metricsTableSparklineDomains([{ key: 'a', values: [null], sparklines: columnValues }], 1)

        const ys = metricsTableSparklineCoordinates(columnValues[0], domain, { width: 96, height: HEIGHT }).map(
            ([, y]) => y
        )

        expect(ys.every((y) => y >= 0 && y <= HEIGHT)).toBe(true)
        expect(new Set(ys).size).toBeGreaterThan(1)
    })

    it('shares one domain across the rows of a column', () => {
        const domains = metricsTableSparklineDomains(
            [
                { key: 'a', values: [null], sparklines: [[-5, 1]] },
                { key: 'b', values: [null], sparklines: [[2, 8]] },
            ],
            1
        )

        expect(domains).toEqual([{ min: -5, max: 8 }])
    })
})
