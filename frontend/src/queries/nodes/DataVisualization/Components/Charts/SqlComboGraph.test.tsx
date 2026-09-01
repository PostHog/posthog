import '@testing-library/jest-dom'

import { cleanup, screen } from '@testing-library/react'

import { clickAtIndex, hoverUntilTooltip, setupJsdom, setupSyncRaf } from '@posthog/quill-charts/testing'

import { renderWithInsights } from '~/test/insight-testing'
import { ChartDisplayType } from '~/types'

import { type AxisSeries } from '../../dataVisualizationLogic'
import { type SqlChartProps } from './SqlChart'
import { SqlComboGraph } from './SqlComboGraph'

let cleanupJsdom: () => void
let cleanupRaf: () => void

beforeEach(() => {
    cleanupJsdom = setupJsdom()
    cleanupRaf = setupSyncRaf()
})

afterEach(() => {
    cleanupRaf()
    cleanupJsdom()
    cleanup()
})

const labels = ['2026-01-01', '2026-01-02', '2026-01-03']

const xData: AxisSeries<string> = {
    column: { name: 'date', type: { name: 'DATE', isNumerical: false }, label: 'date', dataIndex: 0 },
    data: labels,
}

const ySeries = (name: string, data: number[], displayType: 'bar' | 'line' = 'bar'): AxisSeries<number | null> => ({
    column: { name, type: { name: 'INTEGER', isNumerical: true }, label: name, dataIndex: 1 },
    data,
    settings: { display: { displayType } },
})

const props = (overrides: Partial<SqlChartProps> = {}): SqlChartProps => ({
    xData,
    yData: [ySeries('metric', [1, 2, 3])],
    visualizationType: ChartDisplayType.ActionsLineGraph,
    chartSettings: {},
    ...overrides,
})

async function chartWrapper(): Promise<HTMLElement> {
    const canvas = await screen.findByLabelText(/chart with/i, {}, { timeout: 5000 })
    return canvas.parentElement!
}

describe('SqlComboGraph', () => {
    it('forwards clicks from the rendered chart to the SQL chart callback contract', async () => {
        const onPointClick = jest.fn()

        renderWithInsights({ component: <SqlComboGraph {...props({ onPointClick })} /> })

        await clickAtIndex(await chartWrapper(), 1, labels.length, 4000)

        expect(onPointClick).toHaveBeenCalledWith('metric-0', 1, '2026-01-02')
    })

    it('shows the inspect hint in the built-in tooltip when click inspection is available', async () => {
        renderWithInsights({ component: <SqlComboGraph {...props({ onPointClick: jest.fn() })} /> })

        const tooltip = await hoverUntilTooltip(await chartWrapper(), 1, labels.length, 4000)

        expect(tooltip.textContent).toContain('Click to inspect persons')
    })
})
