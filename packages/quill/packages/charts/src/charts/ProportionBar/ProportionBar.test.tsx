import { fireEvent } from '@testing-library/react'

import type { RadialSlicePayload } from '../../core/hooks/useRadialInteraction'
import type { ChartTheme, Series } from '../../core/types'
import { mockRect, renderHogChart, waitForHogChartTooltip } from '../../testing'
import { ProportionBar } from './ProportionBar'

const THEME: ChartTheme = { colors: ['#22d3ee', '#f14f58', '#a78bfa'], backgroundColor: '#ffffff' }

// 600 + 100 + 100 over the 800px mock rect, so part `b` spans x 600..700. With `a` hidden, `b` and `c`
// share the bar and `b` spans x 0..400.
const PARTS: Series[] = [
    { key: 'a', label: 'a', data: [600] },
    { key: 'b', label: 'b', data: [100] },
    { key: 'c', label: 'c', data: [100] },
]
const at = (clientX: number): { clientX: number; clientY: number } => ({ clientX, clientY: mockRect.height / 2 })
const INSIDE_B = at(650)

describe('ProportionBar', () => {
    it('hands the tooltip the hovered part with its raw value, like a pie', async () => {
        const { chart } = renderHogChart(<ProportionBar series={PARTS} theme={THEME} />)

        await waitForHogChartTooltip(3000, () => fireEvent.mouseMove(chart.element, INSIDE_B))
        const ctx = (await chart.waitForTooltip()).seriesData

        expect(ctx).toHaveLength(1)
        expect(ctx[0]).toMatchObject({ series: { key: 'b' }, value: 100, fraction: 0.125 })
    })

    it.each([
        { name: 'all parts drawn', hidden: [], cursor: INSIDE_B, sliceIndex: 1, fraction: 0.125 },
        { name: 'a hidden part before it', hidden: ['a'], cursor: at(200), sliceIndex: 0, fraction: 0.5 },
    ])('reports the clicked part like a pie slice, with $name', async ({ hidden, cursor, sliceIndex, fraction }) => {
        const onSliceClick = jest.fn()
        const { chart } = renderHogChart(
            <ProportionBar
                series={PARTS}
                theme={THEME}
                config={{ legend: { defaultHiddenKeys: hidden } }}
                onSliceClick={onSliceClick}
            />
        )

        await waitForHogChartTooltip(3000, () => fireEvent.mouseMove(chart.element, cursor))
        fireEvent.click(chart.element)

        const payload: RadialSlicePayload = onSliceClick.mock.calls[0][0]
        expect(payload).toMatchObject({ sliceIndex, value: 100, fraction, series: { key: 'b', data: [100] } })
        expect(payload.series.color).toBe(THEME.colors[1])
    })

    it('does not fire onSliceClick for a part with no value, like a pie draws no slice for it', async () => {
        const onSliceClick = jest.fn()
        const zeroParts: Series[] = [
            { key: 'a', label: 'a', data: [0] },
            { key: 'b', label: 'b', data: [0] },
        ]
        const { chart } = renderHogChart(<ProportionBar series={zeroParts} theme={THEME} onSliceClick={onSliceClick} />)

        fireEvent.click(chart.element)

        expect(onSliceClick).not.toHaveBeenCalled()
    })

    it('recomputes the legend shares over the parts left visible', () => {
        const { chart } = renderHogChart(<ProportionBar series={PARTS} theme={THEME} />)
        expect(chart.proportionLegendItems().map((item) => item.secondaryLabel)).toEqual([
            '75% · 600',
            '12.5% · 100',
            '12.5% · 100',
        ])

        chart.clickLegendItem('a', { additive: true })

        expect(chart.proportionLegendItems().map((item) => item.secondaryLabel)).toEqual([
            null,
            '50% · 100',
            '50% · 100',
        ])
    })
})
