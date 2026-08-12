import '@testing-library/jest-dom'

import { cleanup, render } from '@testing-library/react'

import { getHogChart, hoverUntilTooltip, setupJsdom, setupSyncRaf } from '@posthog/quill-charts/testing'

import { initKeaTests } from '~/test/init'

import type { ProcessedChartData, ProcessedTimeseriesDataPoint } from '../../experimentTimeseriesLogic'
import { VariantTimeseriesChart } from './VariantTimeseriesChart'

let cleanupJsdom: () => void
let cleanupRaf: () => void

beforeEach(() => {
    cleanupJsdom = setupJsdom()
    cleanupRaf = setupSyncRaf()
    initKeaTests()
})

afterEach(() => {
    cleanupRaf()
    cleanupJsdom()
    cleanup()
})

const POINTS: ProcessedTimeseriesDataPoint[] = [
    {
        date: '2026-06-01',
        value: 0.04,
        lower_bound: 0.01,
        upper_bound: 0.07,
        hasRealData: true,
        number_of_samples: 1200,
        significant: true,
    },
    {
        date: '2026-06-02',
        value: 0.06,
        lower_bound: 0.03,
        upper_bound: 0.09,
        hasRealData: true,
        number_of_samples: 2400,
        significant: true,
    },
    // Not computed yet — the logic carries the previous day's value forward.
    {
        date: '2026-06-03',
        value: 0.06,
        lower_bound: 0.03,
        upper_bound: 0.09,
        hasRealData: false,
        number_of_samples: 2400,
        significant: true,
    },
]

const CHART_DATA: ProcessedChartData = {
    labels: POINTS.map((point) => point.date),
    processedData: POINTS,
    computedAt: null,
    variantColor: '#1d4aff',
}

function renderChart(): void {
    render(<VariantTimeseriesChart chartData={CHART_DATA} />)
}

describe('VariantTimeseriesChart', () => {
    it('draws the delta line with a confidence interval band', () => {
        renderChart()
        // The delta series plus the band derived from it — a mismatched CI `seriesKey` would
        // silently drop the band and leave one series.
        expect(getHogChart().seriesCount).toBe(2)
    })

    it('labels the value axis as whole percentages', () => {
        renderChart()
        // Deltas arrive as fractions, so the axis needs the 0–1 percentage format; the 0–100 one
        // would render 0.06 as "0.06%".
        expect(getHogChart().yTicks()).toContain('6%')
    })

    it('shows the hovered day in the tooltip', async () => {
        renderChart()
        const tooltip = await hoverUntilTooltip(getHogChart().element, 1, POINTS.length)

        expect(tooltip).toHaveTextContent('Jun 2, 2026')
        expect(tooltip).toHaveTextContent('6.00%')
        expect(tooltip).toHaveTextContent('3.00% → 9.00%')
        expect(tooltip).toHaveTextContent('2,400')
    })
})
