import '@testing-library/jest-dom'

import { cleanup, render } from '@testing-library/react'

import { initKeaTests } from '~/test/init'
import { ChartDisplayType } from '~/types'

import { AxisSeries } from '../../dataVisualizationLogic'
import { LineGraph, type LineGraphProps } from './LineGraph'

let capturedConfig: any = null

jest.mock('lib/hooks/useChart', () => ({
    useChart: ({ getConfig }: { getConfig: () => any }) => {
        capturedConfig = getConfig()
        return { canvasRef: { current: null }, chartRef: { current: null } }
    },
}))

jest.mock('lib/hooks/useResizeObserver', () => ({
    useResizeObserver: () => ({ ref: jest.fn(), height: 400 }),
}))

jest.mock('lib/hooks/useKeyHeld', () => ({
    useKeyHeld: () => false,
}))

jest.mock('scenes/insights/useInsightTooltip', () => ({
    useInsightTooltip: () => ({
        tooltipId: 'test-tooltip',
        getTooltip: () => [{ render: jest.fn() }, document.createElement('div')],
        showTooltip: jest.fn(),
        hideTooltip: jest.fn(),
        positionTooltip: jest.fn(),
        pinTooltip: jest.fn(),
    }),
    unpinTooltip: jest.fn(),
}))

const xData: AxisSeries<string> = {
    column: {
        name: 'day',
        type: { name: 'DATE', isNumerical: false },
        label: 'Day',
        dataIndex: 0,
    },
    data: ['2026-03-01', '2026-03-02'],
}

const yData: AxisSeries<number | null>[] = [
    {
        column: {
            name: 'value',
            type: { name: 'INTEGER', isNumerical: true },
            label: 'Value',
            dataIndex: 1,
        },
        data: [1234, 0],
        settings: {
            formatting: {
                prefix: '$',
                suffix: '',
                style: 'number',
            },
        },
    },
    {
        column: {
            name: 'secondary',
            type: { name: 'INTEGER', isNumerical: true },
            label: 'Secondary',
            dataIndex: 2,
        },
        data: [200, 100],
        settings: {
            formatting: {
                prefix: '',
                suffix: '',
            },
        },
    },
]

const makeProps = (overrides?: Partial<LineGraphProps>): LineGraphProps => ({
    xData,
    yData,
    visualizationType: ChartDisplayType.ActionsBar,
    chartSettings: {
        showValuesOnSeries: false,
    },
    ...overrides,
})

describe('DataVisualization LineGraph', () => {
    beforeEach(() => {
        initKeaTests()
        capturedConfig = null
    })

    afterEach(() => {
        cleanup()
        jest.clearAllMocks()
    })

    it.each([
        {
            showValuesOnSeries: false,
            cases: [{ data: [1234, 0], dataIndex: 0, expected: false }],
        },
        {
            showValuesOnSeries: true,
            cases: [
                { data: [1234, 0], dataIndex: 0, expected: 'auto' },
                { data: [1234, 0], dataIndex: 1, expected: false },
            ],
        },
    ])(
        'uses showValuesOnSeries=$showValuesOnSeries to control datalabel visibility',
        ({ showValuesOnSeries, cases }) => {
            render(
                <LineGraph
                    {...makeProps({
                        chartSettings: {
                            showValuesOnSeries,
                        },
                    })}
                />
            )

            const display = capturedConfig.options.plugins.datalabels.display

            for (const { data, dataIndex, expected } of cases) {
                expect(display({ dataset: { data }, dataIndex })).toBe(expected)
            }
        }
    )

    it('formats datalabels using series formatting', () => {
        render(
            <LineGraph
                {...makeProps({
                    chartSettings: {
                        showValuesOnSeries: true,
                    },
                })}
            />
        )

        const formatter = capturedConfig.options.plugins.datalabels.formatter

        expect(formatter(1234, { datasetIndex: 0, dataIndex: 0, chart: { data: {} } })).toBe('$1,234')
        expect(formatter(0, { datasetIndex: 0, dataIndex: 1, chart: { data: {} } })).toBe('')
    })

    it('formats stacked 100% datalabels as percentages', () => {
        render(
            <LineGraph
                {...makeProps({
                    visualizationType: ChartDisplayType.ActionsStackedBar,
                    chartSettings: {
                        showValuesOnSeries: true,
                        stackBars100: true,
                    },
                })}
            />
        )

        const formatter = capturedConfig.options.plugins.datalabels.formatter

        expect(
            formatter(100, {
                datasetIndex: 1,
                dataIndex: 0,
                chart: { data: { calculatedData: [[60], [40.125]] } },
            })
        ).toBe('40.1%')
    })
})
