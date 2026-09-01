import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import type {
    ChartTheme,
    PointClickData,
    Series,
    TimeSeriesComboChartConfig,
    TimeSeriesComboChartProps,
} from '@posthog/quill-charts'

import { ChartDisplayType } from '~/types'

import { type AxisSeries } from '../../dataVisualizationLogic'
import { type SqlChartProps } from './SqlChart'
import { SqlComboGraph } from './SqlComboGraph'
import { type SqlLineSeriesMeta } from './sqlLineGraphAdapter'
import { type SqlChartModel, useSqlChartModel } from './useSqlChartModel'

let latestComboProps: TimeSeriesComboChartProps<SqlLineSeriesMeta> | null = null

jest.mock('posthog-js', () => ({
    __esModule: true,
    default: { captureException: jest.fn() },
}))

jest.mock('@posthog/quill-charts', () => ({
    ...jest.requireActual('@posthog/quill-charts'),
    TimeSeriesComboChart: (props: TimeSeriesComboChartProps<SqlLineSeriesMeta>): JSX.Element => {
        latestComboProps = props
        return <div data-attr="mock-sql-combo-chart" />
    },
}))

jest.mock('./useSqlChartModel', () => ({
    useSqlChartModel: jest.fn(),
}))

const mockUseSqlChartModel = jest.mocked(useSqlChartModel)

const xData: AxisSeries<string> = {
    column: { name: 'date', type: { name: 'DATE', isNumerical: false }, label: 'date', dataIndex: 0 },
    data: ['2026-01-01'],
}

const series: Series<SqlLineSeriesMeta>[] = [{ key: 'metric-0', label: 'Metric', data: [42], meta: {} }]

const model: SqlChartModel<TimeSeriesComboChartConfig> = {
    series,
    labels: xData.data,
    theme: {} as ChartTheme,
    config: { tooltip: { showTotal: true } },
}

const props = (overrides: Partial<SqlChartProps> = {}): SqlChartProps => ({
    xData,
    yData: [],
    visualizationType: ChartDisplayType.ActionsLineGraph,
    chartSettings: {},
    ...overrides,
})

describe('SqlComboGraph', () => {
    beforeEach(() => {
        latestComboProps = null
        mockUseSqlChartModel.mockReturnValue(model)
    })

    afterEach(() => {
        cleanup()
        mockUseSqlChartModel.mockReset()
    })

    it('passes clicked points through the SQL chart callback contract', async () => {
        const onPointClick = jest.fn()

        render(<SqlComboGraph {...props({ onPointClick })} />)
        await screen.findByTestId('mock-sql-combo-chart')

        const point: PointClickData<SqlLineSeriesMeta> = {
            seriesIndex: 0,
            dataIndex: 0,
            series: series[0],
            value: 42,
            label: '2026-01-01',
            crossSeriesData: [{ series: series[0], value: 42 }],
            cursor: null,
        }
        latestComboProps?.onPointClick?.(point)

        expect(onPointClick).toHaveBeenCalledWith('metric-0', 0, '2026-01-01')
        expect(latestComboProps?.tooltip).toEqual(expect.any(Function))
    })

    it('leaves click handling and the inspect tooltip off when no callback is supplied', async () => {
        render(<SqlComboGraph {...props()} />)
        await screen.findByTestId('mock-sql-combo-chart')

        expect(latestComboProps?.onPointClick).toBeUndefined()
        expect(latestComboProps?.tooltip).toBeUndefined()
    })
})
