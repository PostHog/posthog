import { act, fireEvent } from '@testing-library/react'

import type { ChartTheme } from '../../core/types'
import { rawDrag, renderChart, waitForChartTooltip } from '../../testing'
import { Histogram, type HistogramProps } from './Histogram'
import type { HistogramBin } from './types'

const THEME: ChartTheme = { colors: ['#1f77b4', '#d62728'], backgroundColor: '#ffffff' }

// Zeroed margins make the plot the whole 800×400 jsdom canvas, so x pixels are 10 per unit over a
// 0..80 domain. The middle bin is six times wider than its neighbours.
const MARGINS = { top: 0, right: 0, bottom: 0, left: 0 }
const BINS: HistogramBin[] = [
    { start: 0, end: 10, count: 4 },
    { start: 10, end: 70, count: 12 },
    { start: 70, end: 80, count: 4 },
]
const MID_Y = 200

function renderHistogram(props: Partial<HistogramProps> = {}): ReturnType<typeof renderChart> {
    return renderChart(
        <Histogram bins={BINS} theme={THEME} {...props} config={{ margins: MARGINS, ...props.config }} />
    )
}

async function hoverAt(wrapper: HTMLElement, x: number): Promise<HTMLElement> {
    return waitForChartTooltip(3000, () =>
        act(() => {
            fireEvent.mouseMove(wrapper, { clientX: x, clientY: MID_Y })
        })
    )
}

describe('Histogram', () => {
    it.each<[string, number, number, { min: number; max: number }]>([
        ['snaps a drag outward to whole bins', 50, 720, { min: 0, max: 80 }],
        ['ends at the exclusive edge when the drag stops on a bin edge', 50, 700, { min: 0, max: 70 }],
        ['selects one bin from a drag inside it', 300, 400, { min: 10, max: 70 }],
    ])('%s', async (_, fromX, toX, expected) => {
        const onRangeSelect = jest.fn()
        const { chart } = renderHistogram({ onRangeSelect })
        await hoverAt(chart.element, 400)

        rawDrag(chart.element, { from: { x: fromX, y: MID_Y }, to: { x: toX, y: MID_Y } })

        expect(onRangeSelect).toHaveBeenCalledTimes(1)
        expect(onRangeSelect).toHaveBeenCalledWith(expected)
    })

    it('selects nothing from a click whose wobble crosses the drag threshold', async () => {
        const onRangeSelect = jest.fn()
        const { chart } = renderHistogram({ onRangeSelect })
        await hoverAt(chart.element, 400)

        rawDrag(chart.element, { from: { x: 300, y: MID_Y }, to: { x: 303, y: MID_Y + 5 } })

        expect(onRangeSelect).not.toHaveBeenCalled()
    })

    it('clears a selection on Escape while the pointer is over a bin', async () => {
        const onRangeSelect = jest.fn()
        const { chart } = renderHistogram({ selectedRange: { min: 10, max: 70 }, onRangeSelect })
        await hoverAt(chart.element, 400)

        act(() => {
            fireEvent.keyDown(window, { key: 'Escape' })
        })

        expect(onRangeSelect).toHaveBeenCalledTimes(1)
        expect(onRangeSelect).toHaveBeenCalledWith(null)
    })

    it.each<[string, HistogramBin[], number, string[]]>([
        // x=650 sits inside the wide middle bin but nearer the last bin's center (750).
        [
            'the bin under the cursor, not the bin with the nearest center',
            BINS,
            650,
            ['10 – 70', '12 (60%)', 'Below 7080%'],
        ],
        // The second bin overlaps the first, so it draws from 10; x=700 is value 13.1.
        [
            'an overlapping bin with the trimmed edges it draws with',
            [
                { start: 0, end: 10, count: 4 },
                { start: 5, end: 15, count: 6 },
            ],
            700,
            ['10 – 15', '6 (60%)'],
        ],
        // The two middle bins are a fifth of a pixel wide, so they share the last bin's column.
        [
            'a column of merged sub-pixel bins with their summed count and range',
            [
                { start: 0, end: 10, count: 4 },
                { start: 10, end: 10.02, count: 3 },
                { start: 10.02, end: 10.04, count: 5 },
                { start: 10.04, end: 80, count: 8 },
            ],
            400,
            ['10 – 80', '16 (80%)', 'Below 80100%'],
        ],
    ])('describes %s', async (_, bins, x, expected) => {
        const { chart } = renderHistogram({ bins })
        const tooltip = await hoverAt(chart.element, x)

        for (const text of expected) {
            expect(tooltip.textContent).toContain(text)
        }
    })

    it('ticks a log axis in 1-2-5 steps in the axis format, dropping labels the edges would clip', () => {
        const bins: HistogramBin[] = [1, 10, 100].map((start) => ({ start: start * 1e6, end: start * 1e7, count: 1 }))
        const { chart } = renderHistogram({ bins, config: { xAxis: { scale: 'log', format: 'duration_ns' } } })

        expect(chart.xTicks()).toEqual(['2ms', '5ms', '10ms', '20ms', '50ms', '100ms', '200ms', '500ms'])
    })
})
