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
        const tooltip = await chart.waitForTooltip()

        expect(tooltip).toMatchObject({ label: 'b', dataIndex: 1 })
        expect(tooltip.seriesData).toHaveLength(1)
        expect(tooltip.seriesData[0]).toMatchObject({ series: { key: 'b' }, value: 100, fraction: 0.125 })
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

    it.each([
        {
            name: 'every part is 0',
            series: [
                { key: 'a', label: 'a', data: [0] },
                { key: 'b', label: 'b', data: [0] },
            ],
            hidden: [],
            secondaryLabels: ['0% · 0', '0% · 0'],
        },
        {
            name: 'the legend hides every part',
            series: PARTS,
            hidden: ['a', 'b', 'c'],
            secondaryLabels: [null, null, null],
        },
    ])(
        'renders an empty bar with no click when $name, like a pie draws no slice',
        ({ series, hidden, secondaryLabels }) => {
            const onSliceClick = jest.fn()
            const onError = jest.fn()
            const { chart } = renderHogChart(
                <ProportionBar
                    series={series}
                    theme={THEME}
                    config={{ legend: { defaultHiddenKeys: hidden } }}
                    onSliceClick={onSliceClick}
                    onError={onError}
                />
            )

            fireEvent.click(chart.element)

            expect(chart.legendItems().map((item) => item.secondaryLabel)).toEqual(secondaryLabels)
            expect(onSliceClick).not.toHaveBeenCalled()
            expect(onError).not.toHaveBeenCalled()
        }
    )

    it('recomputes the legend shares over the parts left visible', () => {
        const { chart } = renderHogChart(<ProportionBar series={PARTS} theme={THEME} />)
        expect(chart.legendItems().map((item) => item.secondaryLabel)).toEqual([
            '75% · 600',
            '12.5% · 100',
            '12.5% · 100',
        ])

        chart.clickLegendItem('a', { additive: true })

        expect(chart.legendItems().map((item) => item.secondaryLabel)).toEqual([null, '50% · 100', '50% · 100'])
    })
})
