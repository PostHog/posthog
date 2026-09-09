import '@testing-library/jest-dom'

import { cleanup, screen, waitFor } from '@testing-library/react'

import { getHogChart, hoverAtIndex, setupJsdom, setupSyncRaf } from '@posthog/quill-charts/testing'

import { buildDataVisualizationQuery, renderDataVisualization } from '~/test/insight-testing'
import { ChartDisplayType } from '~/types'

let cleanupJsdom: () => void
let cleanupRaf: () => void

beforeEach(() => {
    cleanupJsdom = setupJsdom()
    cleanupRaf = setupSyncRaf()
})

afterEach(() => {
    cleanupRaf()
    cleanupJsdom()
    cleanup()
})

describe('SqlMetricCard', () => {
    it('renders the latest numeric value and sparkline with SQL formatting', async () => {
        const { container } = renderDataVisualization({
            query: buildDataVisualizationQuery({
                display: ChartDisplayType.Metric,
                chartSettings: {
                    xAxis: { column: 'day' },
                    yAxis: [
                        {
                            column: 'revenue',
                            settings: { formatting: { style: 'number', prefix: '$', decimalPlaces: 0 } },
                        },
                    ],
                },
            }),
            response: {
                columns: ['day', 'revenue'],
                types: [
                    ['day', 'Date'],
                    ['revenue', 'Float64'],
                ],
                results: [
                    ['2026-01-04', null],
                    ['2026-01-03', 1500],
                    ['2026-01-02', null],
                    ['2026-01-01', 1000],
                ],
            },
        })

        await waitFor(() => expect(screen.getByText('$1,500')).toBeInTheDocument())
        expect(screen.getByText('2026-01-03')).toBeInTheDocument()
        expect(container.querySelector('[data-attr="metric-card-sparkline"]')).toBeInTheDocument()

        hoverAtIndex(getHogChart(container).element, 1, 3)
        await waitFor(() => expect(screen.getByText('2026-01-02')).toBeInTheDocument())
    })
})
