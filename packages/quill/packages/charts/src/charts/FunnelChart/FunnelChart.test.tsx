import { fireEvent, waitFor } from '@testing-library/react'

import type { ChartTheme, Series } from '../../core/types'
import { createDefaultTooltipAccessor, renderHogChart } from '../../testing'
import { dimensions } from '../../testing/jsdom'
import { funnelFromCounts } from './funnel-data'
import { FunnelChart, type FunnelStepClickData } from './FunnelChart'

const THEME: ChartTheme = {
    colors: ['#1f77b4', '#ff7f0e'],
    backgroundColor: '#ffffff',
    gridColor: '#eeeeee',
    crosshairColor: '#888888',
}

const STEPS = ['Exposure', 'Purchase']
const SERIES: Series[] = [
    { key: 'control', label: 'control', data: [100, 22] },
    { key: 'test', label: 'test', data: [100, 28] },
]

describe('FunnelChart', () => {
    it('keeps steps with the same display name on separate bands', () => {
        // Bands are keyed by step index; keying by name would collapse both `Pageview`
        // steps into one d3 band slot and the funnel would lose a step.
        const { chart } = renderHogChart(
            <FunnelChart
                steps={['Pageview', 'Pageview']}
                series={[{ key: 'all', label: 'All', data: [100, 40] }]}
                theme={THEME}
            />
        )
        expect(chart.xTicks()).toEqual(['Pageview', 'Pageview'])
    })

    it('formats the value axis as percentages by default', () => {
        const { chart } = renderHogChart(<FunnelChart steps={STEPS} series={SERIES} theme={THEME} />)
        const ticks = chart.yTicks()
        expect(ticks.length).toBeGreaterThan(0)
        expect(ticks.every((tick) => tick.endsWith('%'))).toBe(true)
    })

    it('tooltip header shows the step name and value is formatted as X.XX%', async () => {
        // nativeTooltip preserves config-level formatters (valueFormatter / labelFormatter);
        // the default renderHogChart path intercepts the tooltip prop and bypasses them.
        const { chart } = renderHogChart(<FunnelChart steps={STEPS} series={SERIES} theme={THEME} />, {
            nativeTooltip: true,
        })
        const step = dimensions.plotWidth / STEPS.length
        // Hover at step-index 1 band center — same x as the onStepClick test, lands in control's sub-band.
        const hoverX = dimensions.plotLeft + step * 1.3
        const hoverY = dimensions.plotTop + dimensions.plotHeight / 2
        await waitFor(() => {
            fireEvent.mouseMove(chart.element, { clientX: hoverX, clientY: hoverY })
            const tooltipEl = document.querySelector('[data-hog-charts-tooltip]') as HTMLElement | null
            expect(tooltipEl?.querySelector('[data-attr="hog-chart-tooltip-label"]')?.textContent?.trim()).toBeTruthy()
        })
        const tooltipEl = document.querySelector('[data-hog-charts-tooltip]') as HTMLElement
        const tooltip = createDefaultTooltipAccessor(tooltipEl)
        // labelFormatter maps band index "2" → steps[1] = "Purchase"
        expect(tooltip.label()).toBe('Purchase')
        // formatPercent: 22 → "22%" (parseFloat(22.toFixed(2)) = 22)
        expect(tooltip.value('control')).toBe('22%')
    })

    it.each([
        // Cursor near the plot top at step 2 is in the hatched track above the short bar.
        { area: 'drop-off track', clientYOffset: 2, converted: false },
        // Cursor near the baseline is inside the bar fill.
        { area: 'bar fill', clientYOffset: dimensions.plotHeight - 2, converted: true },
    ])('onStepClick maps a click on the $area to converted=$converted', ({ clientYOffset, converted }) => {
        const onStepClick = jest.fn()
        const { chart } = renderHogChart(
            <FunnelChart steps={STEPS} series={SERIES} theme={THEME} onStepClick={onStepClick} />
        )
        const step = dimensions.plotWidth / STEPS.length
        fireEvent.mouseMove(chart.element, {
            clientX: dimensions.plotLeft + step * 1.3,
            clientY: dimensions.plotTop + clientYOffset,
        })
        fireEvent.click(chart.element)
        const click: FunnelStepClickData = onStepClick.mock.calls[0][0]
        expect(click.stepIndex).toBe(1)
        expect(click.converted).toBe(converted)
    })

    it('renders one step-footer cell per step and hides the axis step labels', async () => {
        const { chart } = renderHogChart(
            <FunnelChart
                steps={STEPS}
                series={SERIES}
                theme={THEME}
                stepFooter={(stepIndex) => <span>{STEPS[stepIndex]}</span>}
            />
        )
        // Footer cells mount once the chart commits its measured band geometry.
        await waitFor(() => {
            const cells = document.querySelectorAll('[data-attr="hog-funnel-step-footer-cell"]')
            expect(cells).toHaveLength(STEPS.length)
        })
        expect(chart.xTicks()).toHaveLength(0)
    })

    it('floors the chart region height with chartMinHeight so a tall footer cannot collapse the canvas', async () => {
        renderHogChart(
            <FunnelChart
                steps={STEPS}
                series={SERIES}
                theme={THEME}
                stepFooter={(stepIndex) => <span>{STEPS[stepIndex]}</span>}
                config={{ chartMinHeight: 150 }}
            />
        )
        await waitFor(() => {
            expect(document.querySelectorAll('[data-attr="hog-funnel-step-footer-cell"]')).toHaveLength(STEPS.length)
        })
        const region = document.querySelector('[data-attr="hog-funnel-chart-region"]') as HTMLElement
        expect(region.style.minHeight).toBe('150px')
    })

    it.each<[string, { label: string; count: number }[], number[]]>([
        [
            'zero basis collapses to 0 instead of NaN',
            [
                { label: 'a', count: 0 },
                { label: 'b', count: 5 },
            ],
            [0, 0],
        ],
        [
            'counts convert to percent of the first step',
            [
                { label: 'a', count: 200 },
                { label: 'b', count: 50 },
            ],
            [100, 25],
        ],
    ])('funnelFromCounts: %s', (_name, counts, expected) => {
        expect(funnelFromCounts(counts).series[0].data).toEqual(expected)
    })
})
