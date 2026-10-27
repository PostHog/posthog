import { fireEvent, screen, within } from '@testing-library/react'

import type { ChartTheme, Series } from '../../core/types'
import { mockRect, renderChart, waitForChartTooltip } from '../../testing'
import { BarList } from './BarList'

const THEME: ChartTheme = { colors: ['#22d3ee', '#f14f58', '#a78bfa', '#fbbf24'], backgroundColor: '#ffffff' }

// The excluded row draws no band, so `a`, `b` and `c` split the 400px mock rect into three rows.
const ROWS: Series[] = [
    { key: 'a', label: 'Row a', data: [600], meta: { id: 'a' } },
    { key: 'excluded', label: 'Excluded row', data: [50], meta: { id: 'excluded' }, visibility: { excluded: true } },
    { key: 'b', label: 'Row b', data: [100], meta: { id: 'b' } },
    { key: 'c', label: 'Row c', data: [100], meta: { id: 'c' } },
]
const INSIDE_B = { clientX: mockRect.width / 2, clientY: mockRect.height / 2 }

describe('BarList', () => {
    it.each([
        { name: 'the sum of the rows', total: undefined, valueText: '12.5% · 100' },
        { name: 'an explicit total', total: 1000, valueText: '10% · 100' },
    ])('shows the hovered row in the tooltip and its share of $name', async ({ total, valueText }) => {
        const { chart } = renderChart(
            <BarList series={ROWS} theme={THEME} total={total} config={{ valueDisplay: 'both' }} />
        )

        const tooltip = await waitForChartTooltip(3000, () => fireEvent.mouseMove(chart.element, INSIDE_B))

        expect(within(tooltip).getByText('Row b')).toBeTruthy()
        expect(within(tooltip).getByText('100')).toBeTruthy()
        expect(screen.getAllByText((_, el) => el?.textContent === valueText)).toHaveLength(2)
    })

    it('hands a custom tooltip the meta of the hovered row', async () => {
        const { chart } = renderChart(<BarList series={ROWS} theme={THEME} tooltip={() => <span>custom</span>} />)

        await waitForChartTooltip(3000, () => fireEvent.mouseMove(chart.element, INSIDE_B))
        const tooltip = await chart.waitForTooltip()

        expect(tooltip.seriesData[0].series.meta).toEqual({ id: 'b' })
    })
})
