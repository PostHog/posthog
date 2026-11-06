import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'

import { setupJsdom, setupSyncRaf } from '@posthog/quill-charts/testing'

import { ChartSettings } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { AxisSeries } from '../../dataVisualizationLogic'
import { SqlScatterGraph } from './SqlScatterGraph'

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

const numericColumn = (name: string, dataIndex: number): AxisSeries<number | null>['column'] => ({
    name,
    type: { name: 'INTEGER', isNumerical: true },
    label: name,
    dataIndex,
})

const xData = (data: (number | null)[]): AxisSeries<string> => ({
    column: numericColumn('session_duration', 0),
    data: data as unknown as string[],
})

const yData = (data: (number | null)[]): AxisSeries<number | null>[] => [
    { column: numericColumn('revenue', 1), data, settings: {} },
]

const chartSettings: ChartSettings = {}

describe('SqlScatterGraph', () => {
    it('renders the chart when points are present', async () => {
        render(<SqlScatterGraph xData={xData([1, 2, 3])} yData={yData([10, 20, 30])} chartSettings={chartSettings} />)

        await waitFor(() => expect(document.querySelector('canvas')).toBeInTheDocument())
        expect(screen.queryByText(/No points to plot/i)).not.toBeInTheDocument()
    })

    it('shows the empty state when no y-series is selected', () => {
        render(<SqlScatterGraph xData={xData([1, 2, 3])} yData={[]} chartSettings={chartSettings} />)

        expect(screen.getByText(/No points to plot/i)).toBeInTheDocument()
    })

    it('shows the empty state when every row is missing a coordinate', () => {
        render(
            <SqlScatterGraph
                xData={xData([1, null, 3])}
                yData={yData([null, 20, null])}
                chartSettings={chartSettings}
            />
        )

        expect(screen.getByText(/No points to plot/i)).toBeInTheDocument()
    })
})
