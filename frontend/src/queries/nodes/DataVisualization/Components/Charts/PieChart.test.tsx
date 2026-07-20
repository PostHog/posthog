import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { setupJsdom, setupSyncRaf } from '@posthog/quill-charts/testing'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

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
    uniqueKey: 'pie-wrapper-test',
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
    it('routes to the quill SqlPieGraph when the quill-sql-charts flag is on', async () => {
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.PRODUCT_ANALYTICS_QUILL_SQL_CHARTS], {
            [FEATURE_FLAGS.PRODUCT_ANALYTICS_QUILL_SQL_CHARTS]: true,
        })

        render(<PieChart {...props} />)

        // The quill PieChart canvas carries this accessible name; the legacy chart.js path does not.
        expect(await screen.findByLabelText(/pie chart with/i, {}, { timeout: 5000 })).toBeInTheDocument()
    })
})
