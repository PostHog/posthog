import '@testing-library/jest-dom'

import { cleanup, render, waitFor } from '@testing-library/react'

import { ensureJsdom, getHogChart, hoverAtIndex, waitForHogChartTooltip } from '@posthog/quill-charts/testing'

import { AppMetricsTimeSeriesChart } from './AppMetricsTimeSeriesChart'

ensureJsdom()

afterEach(cleanup)

describe('AppMetricsTimeSeriesChart', () => {
    it('distinguishes repeated local hours in the tooltip', async () => {
        const labels = ['2026-11-01T01:00:00-07:00', '2026-11-01T01:00:00-08:00']
        const { container } = render(
            <div className="h-64 w-96">
                <AppMetricsTimeSeriesChart
                    timeSeries={{
                        labels,
                        interval: 'hour',
                        timezone: 'US/Pacific',
                        series: [{ name: 'success', values: [2, 3] }],
                    }}
                />
            </div>
        )
        const chart = getHogChart(container)

        hoverAtIndex(chart.element, 0, labels.length)
        const tooltip = await waitForHogChartTooltip()
        expect(tooltip).toHaveTextContent('Sun, Nov 1, 01:00 (-07:00)')

        hoverAtIndex(chart.element, 1, labels.length)
        await waitFor(() => expect(tooltip).toHaveTextContent('Sun, Nov 1, 01:00 (-08:00)'))
    })
})
