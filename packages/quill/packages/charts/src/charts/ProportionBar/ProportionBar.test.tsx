import { act, fireEvent, screen } from '@testing-library/react'

import type { RadialSlicePayload } from '../../core/hooks/useRadialInteraction'
import type { ChartTheme, Series } from '../../core/types'
import { mockRect, renderHogChart, waitForHogChartTooltip } from '../../testing'
import { ProportionBar } from './ProportionBar'

const THEME: ChartTheme = { colors: ['#22d3ee', '#f14f58', '#a78bfa'], backgroundColor: '#ffffff' }

// 600 + 100 + 100 over the 800px mock rect, so part `b` spans x 600..700.
const PARTS: Series[] = [
    { key: 'a', label: 'a', data: [600] },
    { key: 'b', label: 'b', data: [100] },
    { key: 'c', label: 'c', data: [100] },
]
const INSIDE_B = { clientX: 650, clientY: mockRect.height / 2 }

describe('ProportionBar', () => {
    it('hands the tooltip the hovered part with its raw value, like a pie', async () => {
        const { chart } = renderHogChart(<ProportionBar series={PARTS} theme={THEME} />)

        await waitForHogChartTooltip(3000, () => fireEvent.mouseMove(chart.element, INSIDE_B))
        const ctx = (await chart.waitForTooltip()).seriesData

        expect(ctx).toHaveLength(1)
        expect(ctx[0]).toMatchObject({ series: { key: 'b' }, value: 100, fraction: 0.125 })
    })

    it('reports the clicked part through onSliceClick', async () => {
        const onSliceClick = jest.fn()
        const { chart } = renderHogChart(<ProportionBar series={PARTS} theme={THEME} onSliceClick={onSliceClick} />)

        await waitForHogChartTooltip(3000, () => fireEvent.mouseMove(chart.element, INSIDE_B))
        fireEvent.click(chart.element)

        const payload: RadialSlicePayload = onSliceClick.mock.calls[0][0]
        expect(payload).toMatchObject({ sliceIndex: 1, value: 100, fraction: 0.125, series: { key: 'b' } })
        expect(payload.series.color).toBe(THEME.colors[1])
    })

    it('recomputes the legend shares over the parts left visible', () => {
        const { chart } = renderHogChart(<ProportionBar series={PARTS} theme={THEME} />)
        expect(chart.proportionLegendItems().map((item) => item.secondaryLabel)).toEqual([
            '75% · 600',
            '12.5% · 100',
            '12.5% · 100',
        ])

        act(() => {
            fireEvent.click(screen.getByText('a').closest('button')!, { metaKey: true })
        })

        expect(chart.proportionLegendItems().map((item) => item.secondaryLabel)).toEqual([
            null,
            '50% · 100',
            '50% · 100',
        ])
    })
})
