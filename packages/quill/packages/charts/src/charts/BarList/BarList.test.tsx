import { fireEvent, screen } from '@testing-library/react'

import type { ChartTheme, Series } from '../../core/types'
import { mockRect, renderHogChart, waitForHogChartTooltip } from '../../testing'
import { BarList } from './BarList'

const THEME: ChartTheme = { colors: ['#22d3ee', '#f14f58', '#a78bfa', '#fbbf24'], backgroundColor: '#ffffff' }

// The excluded row draws no band, so `a`, `b` and `c` split the 400px mock rect into three rows.
const ROWS: Series[] = [
    { key: 'a', label: 'a', data: [600] },
    { key: 'excluded', label: 'excluded', data: [50], visibility: { excluded: true } },
    { key: 'b', label: 'b', data: [100] },
    { key: 'c', label: 'c', data: [100] },
]
const INSIDE_B = { clientX: mockRect.width / 2, clientY: mockRect.height / 2 }

describe('BarList', () => {
    it.each([
        { name: 'the sum of the rows', total: undefined, fraction: 0.125, valueText: '12.5% · 100' },
        { name: 'an explicit total', total: 1000, fraction: 0.1, valueText: '10% · 100' },
    ])('hands the tooltip the hovered row as a share of $name', async ({ total, fraction, valueText }) => {
        const { chart } = renderHogChart(
            <BarList series={ROWS} theme={THEME} total={total} config={{ valueDisplay: 'both' }} />
        )

        await waitForHogChartTooltip(3000, () => fireEvent.mouseMove(chart.element, INSIDE_B))
        const tooltip = await chart.waitForTooltip()

        expect(tooltip).toMatchObject({ label: 'b', dataIndex: 2 })
        expect(tooltip.seriesData).toHaveLength(1)
        expect(tooltip.seriesData[0]).toMatchObject({
            series: { key: 'b', color: THEME.colors[2] },
            value: 100,
            fraction,
        })
        expect(screen.getAllByText((_, el) => el?.textContent === valueText)).toHaveLength(2)
    })
})
