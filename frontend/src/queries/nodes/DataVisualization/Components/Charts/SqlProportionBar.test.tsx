import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { getHogChart, mockRect, setupJsdom, setupSyncRaf, waitForHogChartTooltip } from '@posthog/quill-charts/testing'

import { ChartSettings } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ChartDisplayType } from '~/types'

import { AxisSeries } from '../../dataVisualizationLogic'
import { SqlChartProps } from './SqlChart'
import { SqlProportionBar } from './SqlProportionBar'

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

const barProps = (chartSettings: ChartSettings, data: (number | null)[]): SqlChartProps => ({
    xData,
    yData: [
        {
            column: { name: 'value', type: { name: 'INTEGER', isNumerical: true }, label: 'value', dataIndex: 1 },
            data,
            settings: {},
        },
    ],
    visualizationType: ChartDisplayType.ActionsProportionBar,
    chartSettings,
})

const withParts = (count: number): SqlChartProps => ({
    ...barProps({}, Array(count).fill(100 / count)),
    xData: { ...xData, data: Array.from({ length: count }, (_, i) => `part ${i}`) },
})

describe('SqlProportionBar', () => {
    it.each([
        {
            name: 'shows its legend shares and the total by default',
            chartSettings: {},
            expectedShares: ['40% · 40', '30% · 30', '20% · 20', '10% · 10'],
            showsTotal: true,
        },
        {
            name: 'hides its legend when the user turns it off',
            chartSettings: { showLegend: false },
            expectedShares: [],
            showsTotal: true,
        },
        {
            name: 'hides the total when showTotal is false',
            chartSettings: { pie: { showTotal: false } },
            expectedShares: ['40% · 40', '30% · 30', '20% · 20', '10% · 10'],
            showsTotal: false,
        },
        {
            name: 'still shows the total when a stale pie sliceContent carries over',
            chartSettings: { pie: { sliceContent: 'labels' as const } },
            expectedShares: ['40% · 40', '30% · 30', '20% · 20', '10% · 10'],
            showsTotal: true,
        },
        {
            name: 'starts with its legend off when it has many parts',
            chartSettings: {},
            partCount: 25,
            expectedShares: [],
            showsTotal: true,
        },
    ])('$name', ({ chartSettings, partCount, expectedShares, showsTotal }) => {
        const props = partCount ? withParts(partCount) : barProps(chartSettings, [40, 30, 20, 10])
        const { container } = render(<SqlProportionBar {...props} />)

        const legendRows = getHogChart(container).legendItems()
        expect(legendRows.map((row) => row.secondaryLabel)).toEqual(expectedShares)
        expect(screen.queryByText('100') !== null).toBe(showsTotal)
    })

    it("shows a part's share in its tooltip, even for a percent-formatted column", async () => {
        const props = barProps({}, [0.2, 0.2])
        props.yData[0].settings = { formatting: { style: 'percent' } }
        const { container } = render(<SqlProportionBar {...props} />)
        const chart = getHogChart(container)

        const tooltip = await waitForHogChartTooltip(3000, () =>
            fireEvent.mouseMove(chart.element, { clientX: mockRect.width / 4, clientY: mockRect.height / 2 })
        )

        expect(tooltip).toHaveTextContent('50%')
    })
})
