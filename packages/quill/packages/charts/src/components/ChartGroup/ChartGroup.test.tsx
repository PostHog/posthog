import { act, cleanup, fireEvent, render, waitFor } from '@testing-library/react'

import { Heatmap } from '../../charts/Heatmap/Heatmap'
import { LineChart } from '../../charts/LineChart/LineChart'
import type { ChartTheme, Series } from '../../core/types'
import {
    clickAtIndex,
    dragSelection,
    ensureJsdom,
    getHogChart,
    HOG_CHARTS_TOOLTIP_SELECTOR,
    hoverUntilTooltip,
} from '../../testing'
import { ChartGroup, type ChartGroupProps } from './ChartGroup'

const THEME: ChartTheme = { colors: ['#111', '#222'], backgroundColor: '#ffffff', crosshairColor: '#999' }
const HOURLY = ['2024-05-01T10:00:00Z', '2024-05-01T11:00:00Z', '2024-05-01T12:00:00Z']
const FIVE_MIN = Array.from({ length: 36 }, (_, i) => new Date(Date.UTC(2024, 4, 1, 10, i * 5)).toISOString())

const hourlySeries: Series[] = [
    { key: 'a', label: 'A', data: [1, 2, 3] },
    { key: 'b', label: 'B', data: [3, 2, 1] },
]
const fineSeries: Series[] = [{ key: 'c', label: 'C', data: FIVE_MIN.map((_, i) => i) }]
const TEN_MIN = Array.from({ length: 18 }, (_, i) => new Date(Date.UTC(2024, 4, 1, 10, i * 10)).toISOString())
const heatmapCells = [TEN_MIN.map(() => 1), TEN_MIN.map(() => 2)]

function renderGroup(props: Omit<ChartGroupProps, 'children'> = {}): {
    hourly: ReturnType<typeof getHogChart>
    fine: ReturnType<typeof getHogChart>
    optedOut: ReturnType<typeof getHogChart>
    heatmap: ReturnType<typeof getHogChart>
} {
    const { container } = render(
        <ChartGroup {...props}>
            <div data-chart="hourly">
                <LineChart
                    series={hourlySeries}
                    labels={HOURLY}
                    theme={THEME}
                    config={{ tooltip: { pinnable: true } }}
                />
            </div>
            <div data-chart="fine">
                <LineChart series={fineSeries} labels={FIVE_MIN} theme={THEME} />
            </div>
            <div data-chart="opted-out">
                <LineChart series={fineSeries} labels={FIVE_MIN} theme={THEME} syncWithGroup={false} />
            </div>
            <div data-chart="heatmap">
                <Heatmap xLabels={TEN_MIN} yLabels={['fast', 'slow']} cells={heatmapCells} theme={THEME} />
            </div>
        </ChartGroup>
    )
    const scope = (name: string): HTMLElement => container.querySelector(`[data-chart="${name}"]`) as HTMLElement
    return {
        hourly: getHogChart(scope('hourly')),
        fine: getHogChart(scope('fine')),
        optedOut: getHogChart(scope('opted-out')),
        heatmap: getHogChart(scope('heatmap')),
    }
}

// The heatmap mirrors no tooltip, because a mirrored hover has no cell under it.
function visibleTooltips(): Element[] {
    return Array.from(document.querySelectorAll(HOG_CHARTS_TOOLTIP_SELECTOR)).filter((el) => el.textContent)
}

describe('ChartGroup', () => {
    beforeEach(() => {
        ensureJsdom()
        cleanup()
        document.querySelectorAll(HOG_CHARTS_TOOLTIP_SELECTOR).forEach((el) => el.remove())
    })

    it('mirrors the hovered time on the other charts and clears it when the pointer leaves', async () => {
        const { hourly, fine, optedOut, heatmap } = renderGroup()
        await hoverUntilTooltip(hourly.element, 0, HOURLY.length)
        const staticRepaint = jest.spyOn(fine.canvas, 'setAttribute')

        await hoverUntilTooltip(hourly.element, 1, HOURLY.length)

        // 11:00 on the hourly chart is the 12th five-minute bucket and the 6th ten-minute column.
        expect(fine.groupHoverIndex()).toBe(12)
        expect(heatmap.groupHoverIndex()).toBe(6)
        expect(hourly.groupHoverIndex()).toBeNull()
        expect(optedOut.groupHoverIndex()).toBeNull()
        expect(staticRepaint).not.toHaveBeenCalledWith('data-hog-charts-paint', 'pending')

        act(() => {
            fireEvent.mouseLeave(hourly.element)
        })
        expect(fine.groupHoverIndex()).toBeNull()
    })

    it('pins the tooltip only on the clicked chart and clears the others when the pointer leaves', async () => {
        const { hourly, fine } = renderGroup({ syncTooltip: 'all' })

        await clickAtIndex(hourly.element, 1, HOURLY.length)

        await waitFor(() => expect(visibleTooltips()).toHaveLength(2))
        expect(document.querySelectorAll('.hog-charts-tooltip--pinned')).toHaveLength(1)

        // The pin outlives the pointer, but the other charts still let go of the hover.
        act(() => {
            fireEvent.mouseLeave(hourly.element)
        })
        expect(fine.groupHoverIndex()).toBeNull()
        expect(visibleTooltips()).toHaveLength(1)
    })

    it('reports a drag on any chart once to the group onZoom', async () => {
        const onZoom = jest.fn()
        const { hourly } = renderGroup({ onZoom })
        await hoverUntilTooltip(hourly.element, 0, HOURLY.length)

        dragSelection(hourly.element, 0, 1, HOURLY.length)

        expect(onZoom).toHaveBeenCalledTimes(1)
        expect(onZoom).toHaveBeenCalledWith({
            startLabel: HOURLY[0],
            endLabel: HOURLY[1],
            from: Date.parse(HOURLY[0]),
            to: Date.parse(HOURLY[2]),
        })
    })
})
