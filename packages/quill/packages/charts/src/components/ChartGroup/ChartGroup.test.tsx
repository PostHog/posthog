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
    trackStaticRepaints,
} from '../../testing'
import { MetricCard } from '../MetricCard/MetricCard'
import { ChartGroup, type ChartGroupProps } from './ChartGroup'

const THEME: ChartTheme = { colors: ['#111', '#222'], backgroundColor: '#ffffff', crosshairColor: '#999' }
const HOURLY = ['2024-05-01T10:00:00Z', '2024-05-01T11:00:00Z', '2024-05-01T12:00:00Z']
const FIVE_MIN = Array.from({ length: 36 }, (_, i) => new Date(Date.UTC(2024, 4, 1, 10, i * 5)).toISOString())
const TEN_MIN = Array.from({ length: 18 }, (_, i) => new Date(Date.UTC(2024, 4, 1, 10, i * 10)).toISOString())
const HALF_HOURLY = ['2024-05-01T10:00:00Z', '2024-05-01T10:30:00Z', '2024-05-01T11:00:00Z', '2024-05-01T11:30:00Z']

const hourlySeries: Series[] = [
    { key: 'a', label: 'A', data: [1, 2, 3] },
    { key: 'b', label: 'B', data: [3, 2, 1] },
]
const fineSeries: Series[] = [{ key: 'c', label: 'C', data: FIVE_MIN.map((_, i) => i) }]
const heatmapCells = [TEN_MIN.map(() => 1), TEN_MIN.map(() => 2)]

type Chart = ReturnType<typeof getHogChart>

function renderGroup(
    props: Omit<ChartGroupProps, 'children'> = {},
    onBrush?: () => void
): { hourly: Chart; fine: Chart; heatmap: Chart; container: HTMLElement } {
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
            <div data-chart="heatmap">
                <Heatmap
                    xLabels={TEN_MIN}
                    yLabels={['fast', 'slow']}
                    cells={heatmapCells}
                    theme={THEME}
                    onBrush={onBrush}
                />
            </div>
            <MetricCard
                title="Requests"
                data={[10, 20, 30, 40]}
                labels={HALF_HOURLY}
                theme={THEME}
                hoverIntentMs={0}
                animationMs={0}
            />
        </ChartGroup>
    )
    const scope = (name: string): HTMLElement => container.querySelector(`[data-chart="${name}"]`) as HTMLElement
    return {
        hourly: getHogChart(scope('hourly')),
        fine: getHogChart(scope('fine')),
        heatmap: getHogChart(scope('heatmap')),
        container,
    }
}

function highlightedRanges(chart: Chart): number {
    return chart.element.querySelectorAll('[data-attr="hog-chart-highlighted-range"]').length
}

describe('ChartGroup', () => {
    beforeEach(() => {
        ensureJsdom()
        cleanup()
        document.querySelectorAll(HOG_CHARTS_TOOLTIP_SELECTOR).forEach((el) => el.remove())
    })

    it('mirrors the hovered time on the other charts and clears it when the pointer leaves', async () => {
        const { hourly, fine, heatmap, container } = renderGroup()
        await hoverUntilTooltip(hourly.element, 0, HOURLY.length)
        const repaints = trackStaticRepaints(fine)

        await hoverUntilTooltip(hourly.element, 1, HOURLY.length)

        // 11:00 on the hourly chart is the 12th five-minute bucket and the 6th ten-minute column.
        expect(fine.groupHoverIndex()).toBe(12)
        expect(heatmap.groupHoverIndex()).toBe(6)
        expect(hourly.groupHoverIndex()).toBeNull()
        expect(container.querySelector('[data-attr="metric-card-subtitle"]')?.textContent).toBe(HALF_HOURLY[2])
        expect(repaints.count()).toBe(0)
        repaints.stop()

        act(() => {
            fireEvent.mouseLeave(hourly.element)
        })
        expect(fine.groupHoverIndex()).toBeNull()
    })

    it('draws no mirrored hover when syncCrosshair is off', async () => {
        const { hourly, fine } = renderGroup({ syncCrosshair: false })

        await hoverUntilTooltip(hourly.element, 1, HOURLY.length)

        expect(fine.groupHoverIndex()).toBeNull()
    })

    it('pins the tooltip only on the clicked chart and clears the others when the pointer leaves', async () => {
        const { hourly, fine } = renderGroup({ syncTooltip: 'all' })

        await clickAtIndex(hourly.element, 1, HOURLY.length)

        // The fine chart mirrors a tooltip; the heatmap has no cell under a mirrored hover, so it mounts none.
        await waitFor(() => expect(document.querySelectorAll(HOG_CHARTS_TOOLTIP_SELECTOR)).toHaveLength(2))
        expect(document.querySelectorAll('.hog-charts-tooltip--pinned')).toHaveLength(1)

        // The pin outlives the pointer, but the other charts still let go of the hover.
        act(() => {
            fireEvent.mouseLeave(hourly.element)
        })
        expect(fine.groupHoverIndex()).toBeNull()
        expect(document.querySelectorAll(HOG_CHARTS_TOOLTIP_SELECTOR)).toHaveLength(1)

        // Coming back to the pinned chart takes the group hover back.
        act(() => {
            fireEvent.mouseMove(hourly.element, { clientX: 400, clientY: 200 })
        })
        expect(fine.groupHoverIndex()).toBe(12)
    })

    it('reports a drag on any time chart once to the group onZoom', async () => {
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

    it('shows a heatmap brush on the other charts until Escape clears it', async () => {
        const onSelectionChange = jest.fn()
        const { heatmap, fine } = renderGroup({ onSelectionChange }, () => {})
        await hoverUntilTooltip(heatmap.element, 0, TEN_MIN.length)

        dragSelection(heatmap.element, 6, 8, TEN_MIN.length)

        expect(onSelectionChange).toHaveBeenLastCalledWith({
            startLabel: TEN_MIN[6],
            endLabel: TEN_MIN[8],
            from: Date.parse(TEN_MIN[6]),
            to: Date.parse(TEN_MIN[9]),
        })
        expect(highlightedRanges(fine)).toBe(1)

        act(() => {
            fireEvent.keyDown(document, { key: 'Escape' })
        })
        expect(onSelectionChange).toHaveBeenLastCalledWith(null)
        expect(highlightedRanges(fine)).toBe(0)
    })
})
