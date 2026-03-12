import { waitFor } from '@testing-library/react'

import { getChart } from './chart-accessor'

export async function waitForChart(expectedDatasets?: number): ReturnType<typeof getChart> {
    let chart: ReturnType<typeof getChart>
    await waitFor(
        () => {
            chart = getChart()
            if (expectedDatasets !== undefined) {
                expect(chart.datasets).toHaveLength(expectedDatasets)
            } else {
                expect(chart.datasets.length).toBeGreaterThan(0)
            }
        },
        { timeout: 5000 }
    )
    return chart!
}
