import { waitFor } from '@testing-library/react'

import { type Chart, getChart } from './chart-accessor'
import { getCapturedChartConfigs } from './chartjs-mock'

/** Wait for a new chart to render. On each call, waits for a chart that
 *  didn't exist when waitForChart was invoked, so back-to-back calls
 *  after interactions always return fresh data. */
export async function waitForChart(): Promise<Chart> {
    const countAtCall = getCapturedChartConfigs().length
    let chart: Chart
    await waitFor(
        () => {
            expect(getCapturedChartConfigs().length).toBeGreaterThan(countAtCall)
            chart = getChart()
            expect(chart.seriesCount).toBeGreaterThan(0)
        },
        { timeout: 2000 }
    )
    return chart!
}
