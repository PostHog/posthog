import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { setupJsdom, setupSyncRaf } from '@posthog/quill-charts/testing'

import { initKeaTests } from '~/test/init'
import { ChartDisplayType } from '~/types'

import { AxisSeries } from '../../dataVisualizationLogic'
import { PartOfWholeChart, PartOfWholeChartProps } from './PartOfWholeChart'

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

const props: PartOfWholeChartProps = {
    xData: {
        column: { name: 'category', type: { name: 'STRING', isNumerical: false }, label: 'category', dataIndex: 0 },
        data: ['alpha', 'beta'],
    } as AxisSeries<string>,
    yData: [
        {
            column: { name: 'value', type: { name: 'INTEGER', isNumerical: true }, label: 'value', dataIndex: 1 },
            data: [60, 40],
            settings: {},
        },
    ],
    visualizationType: ChartDisplayType.ActionsPie,
    chartSettings: {},
}

describe('PartOfWholeChart', () => {
    it('renders the quill SqlPieGraph', async () => {
        render(<PartOfWholeChart {...props} />)

        // The quill PieChart canvas carries this accessible name.
        expect(await screen.findByLabelText(/pie chart with/i, {}, { timeout: 5000 })).toBeInTheDocument()
    })

    it('renders a donut total in the chart center', async () => {
        render(
            <PartOfWholeChart
                {...props}
                visualizationType={ChartDisplayType.ActionsDonut}
                chartSettings={{ pie: { sliceContent: 'labels', showTotal: true } }}
            />
        )

        await screen.findByLabelText(/pie chart with/i, {}, { timeout: 5000 })

        expect((await screen.findByText('100')).closest('[data-attr="sql-pie-chart"]')).toBeInTheDocument()
    })

    it('renders a proportion bar for the proportion bar display', () => {
        const { container } = render(
            <PartOfWholeChart {...props} visualizationType={ChartDisplayType.ActionsProportionBar} />
        )

        expect(container.querySelector('[data-attr="sql-proportion-bar"]')).toBeInTheDocument()
    })
})
