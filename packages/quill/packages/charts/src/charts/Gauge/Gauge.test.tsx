import { fireEvent } from '@testing-library/react'

import { ChartThemeProvider } from '../../core/theme'
import type { ChartTheme } from '../../core/types'
import { createDefaultTooltipAccessor, renderChart, waitForChartTooltip } from '../../testing'
import type { DefaultTooltipAccessor } from '../../testing'
import { Gauge } from './Gauge'

const THEME: ChartTheme = { colors: ['#111111'], backgroundColor: '#ffffff' }
const THRESHOLDS = [
    { value: 90, color: '#ff0000', label: 'Critical' },
    { value: 0, color: '#00ff00', label: 'Healthy' },
    { value: 70, color: '#ffaa00', label: 'Busy' },
]

async function hoverGauge(element: HTMLElement): Promise<DefaultTooltipAccessor> {
    const rect = element.getBoundingClientRect()
    fireEvent.mouseMove(element, { clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2 })
    return createDefaultTooltipAccessor(await waitForChartTooltip())
}

describe('Gauge', () => {
    beforeEach(() => {
        document.body.style.setProperty('--gauge-test-busy', '#ffaa00')
    })

    afterEach(() => {
        document.body.style.removeProperty('--gauge-test-busy')
    })

    it('shows a dash and no threshold for a null value, not a zero', async () => {
        const { chart } = renderChart(
            <Gauge value={null} min={0} max={100} thresholds={THRESHOLDS} theme={THEME} label="CPU" />
        )

        expect(chart.gauge.text()).toEqual({ value: '–', label: 'CPU', min: '0', max: '100' })
        const tooltip = await hoverGauge(chart.element)
        expect(tooltip.rows()).toEqual(['Value', 'Range'])
    })

    it('reports the threshold band the value falls in, whatever order the thresholds come in', async () => {
        const { chart } = renderChart(
            <Gauge
                value={78}
                min={0}
                max={100}
                thresholds={THRESHOLDS}
                theme={THEME}
                config={{ valueFormatter: (v) => `${v}%` }}
            />
        )

        expect(chart.gauge.text()).toMatchObject({ value: '78%', min: '0%', max: '100%' })
        expect(chart.gauge.valueColor()).toBe('rgb(255, 170, 0)')
        const tooltip = await hoverGauge(chart.element)
        expect(tooltip.value('Threshold')).toBe('Busy · 70% – 90%')
        expect(tooltip.swatchColors()).toContain('rgb(255, 170, 0)')
        expect(await chart.waitForTooltip()).toMatchObject({
            value: 78,
            min: 0,
            max: 100,
            threshold: { threshold: { label: 'Busy' } },
        })
    })

    it('takes its theme from the nearest ChartThemeProvider when no theme prop is set', () => {
        const { chart } = renderChart(
            <ChartThemeProvider value={THEME}>
                <Gauge value={50} min={0} max={100} />
            </ChartThemeProvider>
        )

        expect(chart.gauge.valueColor()).toBe('rgb(17, 17, 17)')
    })

    it('resolves var() threshold colors again when the theme changes', async () => {
        const thresholds = [
            { value: 0, color: '#00ff00' },
            { value: 70, color: 'var(--gauge-test-busy)' },
        ]
        const { chart, rerender } = renderChart(
            <Gauge value={78} min={0} max={100} thresholds={thresholds} theme={THEME} />
        )
        expect((await hoverGauge(chart.element)).swatchColors()).toContain('rgb(255, 170, 0)')

        document.body.style.setProperty('--gauge-test-busy', '#0000ff')
        rerender(<Gauge value={78} min={0} max={100} thresholds={thresholds} theme={{ ...THEME }} />)
        expect((await hoverGauge(chart.element)).swatchColors()).toContain('rgb(0, 0, 255)')
    })
})
