import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { getHogChart, setupJsdom, setupSyncRaf } from '@posthog/quill-charts/testing'

import { ChartSettings } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ChartDisplayType } from '~/types'

import { AxisSeries } from '../../dataVisualizationLogic'
import { AxisBreakdownSeries } from '../seriesBreakdownLogic'
import { SqlChartProps } from './SqlChart'
import { SqlPieGraph } from './SqlPieGraph'

let cleanupJsdom: () => void
let cleanupRaf: () => void

beforeEach(() => {
    initKeaTests()
    cleanupJsdom = setupJsdom()
    cleanupRaf = setupSyncRaf()
})

afterEach(() => {
    cleanupRaf()
    cleanupJsdom()
    cleanup()
})

const xData: AxisSeries<string> = {
    column: { name: 'category', type: { name: 'STRING', isNumerical: false }, label: 'category', dataIndex: 0 },
    data: ['alpha', 'beta', 'gamma', 'delta'],
}

const yData = (data: (number | null)[]): AxisSeries<number | null>[] => [
    {
        column: { name: 'value', type: { name: 'INTEGER', isNumerical: true }, label: 'value', dataIndex: 1 },
        data,
        settings: {},
    },
]

const baseProps = (
    chartSettings: ChartSettings,
    data: (number | null)[],
    visualizationType = ChartDisplayType.ActionsPie
): SqlChartProps => ({
    xData,
    yData: yData(data),
    visualizationType,
    chartSettings,
})

// Equal parts that add up to 100, one category each.
const proportionBarWithParts = (count: number): SqlChartProps => ({
    ...baseProps({}, Array(count).fill(100 / count), ChartDisplayType.ActionsProportionBar),
    xData: { ...xData, data: Array.from({ length: count }, (_, i) => `part ${i}`) },
})

// On-slice labels are static overlay nodes (not pointer-driven), so they steer clear of the
// quill PieChart's flaky hover/click interaction tests. Each slice renders one <div> per line
// (label and/or value), so we read the lines per slice rather than the concatenated text.
function sliceLabelLines(): string[][] {
    return Array.from(document.querySelectorAll('[data-attr="hog-chart-pie-slice-label"]')).map((el) =>
        Array.from(el.querySelectorAll('div')).map((line) => line.textContent!)
    )
}

async function waitForSlices(): Promise<void> {
    await screen.findByLabelText(/pie chart with/i, {}, { timeout: 5000 })
    await waitFor(
        () => {
            if (sliceLabelLines().length === 0) {
                throw new Error('slice labels not rendered yet')
            }
        },
        { timeout: 5000 }
    )
}

describe('SqlPieGraph', () => {
    it('defaults to values and the total when slice content is unset (existing chart)', async () => {
        render(<SqlPieGraph {...baseProps({}, [40, 30, 20, 10])} />)

        await waitForSlices()

        // Unset slice content means a pre-existing chart, which keeps the legacy value-on-slice + total
        expect(sliceLabelLines()).toEqual([['40'], ['30'], ['20'], ['10']])
        expect(screen.getByText('100')).toBeInTheDocument()
    })

    it('shows slice labels and hides the total when slice content is labels', async () => {
        render(<SqlPieGraph {...baseProps({ pie: { sliceContent: 'labels' } }, [40, 30, 20, 10])} />)

        await waitForSlices()

        expect(sliceLabelLines()).toEqual([['alpha'], ['beta'], ['gamma'], ['delta']])
        expect(screen.queryByText('100')).not.toBeInTheDocument()
    })

    it('respects an explicit showTotal override that hides the total in values mode', async () => {
        render(<SqlPieGraph {...baseProps({ pie: { sliceContent: 'values', showTotal: false } }, [40, 30, 20, 10])} />)

        await waitForSlices()

        expect(sliceLabelLines()).toEqual([['40'], ['30'], ['20'], ['10']])
        expect(screen.queryByText('100')).not.toBeInTheDocument()
    })

    it.each([
        {
            name: 'a proportion bar shows its legend shares and the total by default',
            chartSettings: {},
            expectedShares: ['40% · 40', '30% · 30', '20% · 20', '10% · 10'],
            showsTotal: true,
        },
        {
            name: 'a proportion bar hides its legend when the user turns it off',
            chartSettings: { showLegend: false },
            expectedShares: [],
            showsTotal: true,
        },
        {
            name: 'a proportion bar hides the total when showTotal is false',
            chartSettings: { pie: { showTotal: false } },
            expectedShares: ['40% · 40', '30% · 30', '20% · 20', '10% · 10'],
            showsTotal: false,
        },
        {
            // `sliceContent` is a pie-only "show on slices" setting with no proportion-bar control,
            // so a value carried over from a prior pie selection must not suppress the bar's total.
            name: 'a proportion bar still shows the total when a stale pie sliceContent carries over',
            chartSettings: { pie: { sliceContent: 'labels' as const } },
            expectedShares: ['40% · 40', '30% · 30', '20% · 20', '10% · 10'],
            showsTotal: true,
        },
        {
            name: 'a proportion bar with many parts starts with its legend off',
            chartSettings: {},
            partCount: 25,
            expectedShares: [],
            showsTotal: true,
        },
    ])('$name', ({ chartSettings, partCount, expectedShares, showsTotal }) => {
        const props = partCount
            ? proportionBarWithParts(partCount)
            : baseProps(chartSettings, [40, 30, 20, 10], ChartDisplayType.ActionsProportionBar)
        const { container } = render(<SqlPieGraph {...props} />)

        const legendRows = getHogChart(container).legendItems()
        expect(legendRows.map((row) => row.secondaryLabel)).toEqual(expectedShares)
        expect(screen.queryByText('100') !== null).toBe(showsTotal)
    })

    it('shows the total in the center of a donut', async () => {
        render(
            <SqlPieGraph
                {...baseProps(
                    { pie: { sliceContent: 'labels', showTotal: true } },
                    [40, 30, 20, 10],
                    ChartDisplayType.ActionsDonut
                )}
            />
        )

        await waitForSlices()

        expect(screen.getByText('100').closest('[data-attr="sql-pie-chart"]')).toBeInTheDocument()
    })

    it('hides the donut center total when showTotal is false', async () => {
        render(
            <SqlPieGraph
                {...baseProps(
                    { pie: { sliceContent: 'labels', showTotal: false } },
                    [40, 30, 20, 10],
                    ChartDisplayType.ActionsDonut
                )}
            />
        )

        await waitForSlices()

        expect(screen.queryByText('100')).not.toBeInTheDocument()
    })

    it('honors the legacy top-level showPieTotal toggle on charts saved before `pie`', async () => {
        // Pre-PR insights stored the toggle as `chartSettings.showPieTotal`. It must still parse and
        // drive the total, otherwise those saved insights regress (validation + missing total).
        render(<SqlPieGraph {...baseProps({ showPieTotal: false }, [40, 30, 20, 10])} />)

        await waitForSlices()

        expect(screen.queryByText('100')).not.toBeInTheDocument()
    })

    it('lets the legacy showPieTotal turn the total on even when slice content hides it by default', async () => {
        // sliceContent 'labels' defaults the total off, so this only shows if the legacy true is honored.
        render(
            <SqlPieGraph {...baseProps({ showPieTotal: true, pie: { sliceContent: 'labels' } }, [40, 30, 20, 10])} />
        )

        await waitForSlices()

        expect(screen.getByText('100')).toBeInTheDocument()
    })

    it('prefers pie.showTotal over the legacy showPieTotal when both are set', async () => {
        // A chart re-saved with the new `pie` block must win over the stale top-level toggle, otherwise
        // toggling the total off in the new UI would silently regress to the legacy value.
        render(<SqlPieGraph {...baseProps({ showPieTotal: true, pie: { showTotal: false } }, [40, 30, 20, 10])} />)

        await waitForSlices()

        expect(screen.queryByText('100')).not.toBeInTheDocument()
    })

    it('shows slice values as shares of the total when displaying percentages', async () => {
        render(
            <SqlPieGraph
                {...baseProps({ pie: { sliceContent: 'values', valueDisplay: 'percentage' } }, [40, 30, 20, 10])}
            />
        )

        await waitForSlices()

        expect(sliceLabelLines()).toEqual([['40%'], ['30%'], ['20%'], ['10%']])
    })

    it('renders nothing on slices when slice content is none', async () => {
        render(<SqlPieGraph {...baseProps({ pie: { sliceContent: 'none' } }, [40, 30, 20, 10])} />)

        await screen.findByLabelText(/pie chart with/i, {}, { timeout: 5000 })

        expect(sliceLabelLines()).toEqual([])
    })

    it("renders quill's legend with one row per slice", () => {
        // The legend is plain DOM outside the canvas, so it needs no canvas paint.
        render(<SqlPieGraph {...baseProps({ showLegend: true }, [60, 40, 0, 0])} />)

        expect(document.querySelector('[data-attr="hog-chart-pie-legend"]')).toBeInTheDocument()
        expect(screen.getByText('alpha')).toBeInTheDocument()
        expect(screen.getByText('beta')).toBeInTheDocument()
    })

    it('restores all slices when the legend is hidden after isolating one', async () => {
        const chartSettings: ChartSettings = { showLegend: true, pie: { sliceContent: 'labels', showTotal: true } }
        const { rerender } = render(<SqlPieGraph {...baseProps(chartSettings, [60, 40, 0, 0])} />)
        const user = userEvent.setup()

        await waitForSlices()
        await user.click(within(document.querySelector('[data-attr="hog-chart-pie-legend"]')!).getByText('alpha'))

        await waitFor(() => {
            expect(sliceLabelLines()).toEqual([['alpha']])
            expect(screen.getByText('60')).toBeInTheDocument()
        })

        rerender(<SqlPieGraph {...baseProps({ ...chartSettings, showLegend: false }, [60, 40, 0, 0])} />)

        await waitFor(() => {
            expect(document.querySelector('[data-attr="hog-chart-pie-legend"]')).not.toBeInTheDocument()
            expect(sliceLabelLines()).toEqual([['alpha'], ['beta']])
            expect(screen.getByText('100')).toBeInTheDocument()
        })
    })

    it('shows the empty state when there are no positive values', () => {
        render(<SqlPieGraph {...baseProps({}, [0, 0, null, 0])} />)

        expect(screen.getByText('Pie charts require at least one positive value.')).toBeInTheDocument()
    })

    it('colors breakdown slices from per-breakdown resultCustomizations', () => {
        // One slice per breakdown series; the legend swatch color must come from
        // settings.display.color (resultCustomizations), not the palette default.
        const breakdownYData: AxisBreakdownSeries<number | null>[] = [
            { name: 'first', breakdownValue: 'first', data: [3, 2], settings: { display: { color: '#aa0000' } } },
            { name: 'second', breakdownValue: 'second', data: [4, 1], settings: { display: { color: '#00aa00' } } },
        ]
        render(
            <SqlPieGraph
                xData={xData}
                yData={breakdownYData}
                visualizationType={ChartDisplayType.ActionsPie}
                chartSettings={{ showLegend: true }}
            />
        )

        const swatchColors = Array.from(
            document.querySelectorAll<HTMLElement>('[data-attr="hog-chart-pie-legend"] span[aria-hidden="true"]')
        ).map((el) => el.style.backgroundColor)
        expect(screen.getByText('first')).toBeInTheDocument()
        expect(swatchColors).toContain('rgb(170, 0, 0)')
        expect(swatchColors).toContain('rgb(0, 170, 0)')
    })
})
