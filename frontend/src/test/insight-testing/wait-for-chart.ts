import { waitFor } from '@testing-library/react'

import { type Chart, getChart } from './chart-accessor'

export async function waitForChart(expectedSeries?: number): Promise<Chart> {
    let chart: Chart
    await waitFor(
        () => {
            chart = getChart()
            if (expectedSeries !== undefined) {
                expect(chart.seriesCount).toBe(expectedSeries)
            } else {
                expect(chart.seriesCount).toBeGreaterThan(0)
            }
        },
        { timeout: 2000 }
    )
    return chart!
}
