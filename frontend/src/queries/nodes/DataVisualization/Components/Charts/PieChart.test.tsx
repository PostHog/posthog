import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { setupJsdom, setupSyncRaf } from '@posthog/quill-charts/testing'

import { initKeaTests } from '~/test/init'

import { AxisSeries } from '../../dataVisualizationLogic'
import { PieChart, PieChartProps } from './PieChart'

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

const props: PieChartProps = {
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
    chartSettings: {},
}

describe('PieChart wrapper', () => {
    it('renders the quill SqlPieGraph', async () => {
        render(<PieChart {...props} />)

        // The quill PieChart canvas carries this accessible name.
        expect(await screen.findByLabelText(/pie chart with/i, {}, { timeout: 5000 })).toBeInTheDocument()
    })
})
