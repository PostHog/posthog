import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'

import type { BoxPlotConfig, BoxPlotSeries } from '@posthog/quill-charts'

import { BoxPlotSettings, ChartSettings } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { Column } from '../../dataVisualizationLogic'
import { SqlBoxPlot } from './SqlBoxPlot'

let latestBoxPlotProps: { labels: string[]; series: BoxPlotSeries[]; config?: BoxPlotConfig } | null = null

jest.mock('posthog-js', () => ({
    __esModule: true,
    default: { capture: jest.fn(), get_session_id: jest.fn(() => 'session-1') },
}))

jest.mock('@posthog/quill-charts', () => ({
    ...jest.requireActual('@posthog/quill-charts'),
    BoxPlot: (props: { labels: string[]; series: BoxPlotSeries[]; config?: BoxPlotConfig }): JSX.Element => {
        latestBoxPlotProps = props
        return <div data-attr="mock-sql-box-plot" />
    },
}))

const posthog = jest.requireMock('posthog-js').default as { capture: jest.Mock }

const columns: Column[] = [
    { name: 'bucket', label: 'bucket', dataIndex: 0, type: { name: 'STRING', isNumerical: false } },
    { name: 'series', label: 'series', dataIndex: 1, type: { name: 'STRING', isNumerical: false } },
    { name: 'min', label: 'min', dataIndex: 2, type: { name: 'FLOAT', isNumerical: true } },
    { name: 'p25', label: 'p25', dataIndex: 3, type: { name: 'FLOAT', isNumerical: true } },
    { name: 'median', label: 'median', dataIndex: 4, type: { name: 'FLOAT', isNumerical: true } },
    { name: 'mean', label: 'mean', dataIndex: 5, type: { name: 'FLOAT', isNumerical: true } },
    { name: 'p75', label: 'p75', dataIndex: 6, type: { name: 'FLOAT', isNumerical: true } },
    { name: 'max', label: 'max', dataIndex: 7, type: { name: 'FLOAT', isNumerical: true } },
]

const boxPlotSettings: BoxPlotSettings = {
    xAxisColumn: 'bucket',
    seriesColumn: 'series',
    minColumn: 'min',
    p25Column: 'p25',
    medianColumn: 'median',
    meanColumn: 'mean',
    p75Column: 'p75',
    maxColumn: 'max',
    excludeOutliers: false,
}

const chartSettings: ChartSettings = { boxPlot: boxPlotSettings }

describe('SqlBoxPlot', () => {
    beforeEach(() => {
        initKeaTests()
        latestBoxPlotProps = null
        posthog.capture.mockClear()
    })

    afterEach(() => {
        cleanup()
    })

    it('renders grouped boxes with the standard axis defaults', async () => {
        render(
            <SqlBoxPlot
                rows={[
                    ['Mon', 'Free', 1, 2, 3, 4, 5, 6],
                    ['Mon', 'Paid', 7, 8, 9, 10, 11, 12],
                ]}
                columns={columns}
                chartSettings={chartSettings}
                analyticsKey="grouped-test"
            />
        )

        await screen.findByTestId('mock-sql-box-plot')
        expect(posthog.capture).not.toHaveBeenCalled()
        expect(latestBoxPlotProps).toMatchObject({
            labels: ['Mon'],
            series: [
                { key: 'Free', label: 'Free' },
                { key: 'Paid', label: 'Paid' },
            ],
            config: {
                showGrid: true,
                showAxisLines: { x: true, y: true },
            },
        })
    })

    it('captures unrendered items once per chart and session while keeping valid boxes', async () => {
        const { rerender } = render(
            <SqlBoxPlot
                rows={[
                    ['Mon', 'Free', 1, null, 3, 4, 5, 6],
                    ['Tue', 'Free', 1, 2, 3, 4, 5, 6],
                ]}
                columns={columns}
                chartSettings={chartSettings}
                analyticsKey="skipped-test"
            />
        )

        await screen.findByTestId('mock-sql-box-plot')
        expect(latestBoxPlotProps).toMatchObject({
            labels: ['Tue'],
            series: [{ key: 'Free', label: 'Free' }],
        })
        await waitFor(() =>
            expect(posthog.capture).toHaveBeenCalledWith('sql box plot items not rendered', {
                unrendered_item_count: 1,
                total_item_count: 2,
                reasons: { missingStatistic: 1, invalidOrder: 0, meanOutsideRange: 0 },
            })
        )

        rerender(
            <SqlBoxPlot
                rows={[
                    ['Mon', 'Free', 1, null, 3, 4, 5, 6],
                    ['Tue', 'Free', 1, null, 3, 4, 5, 6],
                ]}
                columns={columns}
                chartSettings={chartSettings}
                analyticsKey="skipped-test"
            />
        )
        await waitFor(() => expect(posthog.capture).toHaveBeenCalledTimes(1))
    })

    it('explains how to fix missing column mappings', () => {
        render(
            <SqlBoxPlot
                rows={[['Mon', 'Free', 1, 2, 3, 4, 5, 6]]}
                columns={columns}
                chartSettings={{ boxPlot: { ...boxPlotSettings, medianColumn: undefined } }}
                analyticsKey="mapping-error-test"
            />
        )

        expect(screen.getByText('Select a column for Median.')).toBeInTheDocument()
        expect(latestBoxPlotProps).toBeNull()
    })
})
