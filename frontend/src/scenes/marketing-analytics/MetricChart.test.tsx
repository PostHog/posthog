import '@testing-library/jest-dom'

import { render } from '@testing-library/react'

import { clickAtIndex, ensureJsdom, getHogChart } from '@posthog/quill-charts/testing'

import { MetricChart, MetricChartProps } from 'products/marketing_analytics/frontend/dashboard/charts/MetricChart'

ensureJsdom()

const props: MetricChartProps = {
    label: 'Visitors',
    breakdownLabel: 'Channel',
    format: 'number',
    timezone: 'UTC',
    labels: ['2026-01-01', '2026-01-02', '2026-01-03'],
    series: [],
    chartMode: 'breakdown',
    focusedBreakdownValue: null,
    loading: false,
    error: null,
    onChartModeChange: jest.fn(),
    onFocus: jest.fn(),
}

describe('MetricChart', () => {
    it.each([
        { key: 'email', label: 'Email newsletter' },
        { key: '', label: 'No channel' },
    ])('reports the raw breakdown key "$key" when a point is selected', async ({ key, label }) => {
        const onFocus = jest.fn()
        const { container } = render(
            <MetricChart {...props} series={[{ key, label, data: [0, 12, 8] }]} onFocus={onFocus} />
        )

        const chart = getHogChart(container)
        await clickAtIndex(chart.element, 1, props.labels.length)

        expect(onFocus).toHaveBeenCalledWith(key)
    })

    it('shows the supplied error instead of stale data and hides it during retry', () => {
        const { container, rerender, getByText, queryByText } = render(
            <MetricChart
                {...props}
                series={[{ key: 'email', label: 'Email', data: [0, 12, 8] }]}
                error={<span>Query ID: synthetic-query-id</span>}
            />
        )

        expect(getByText('Query ID: synthetic-query-id')).toBeVisible()
        expect(container.querySelector('canvas')).not.toBeInTheDocument()

        rerender(<MetricChart {...props} loading error={<span>Query ID: synthetic-query-id</span>} />)

        expect(queryByText('Query ID: synthetic-query-id')).not.toBeInTheDocument()
        expect(container.querySelector('[aria-label="Loading chart"]')).toBeVisible()
    })
})
