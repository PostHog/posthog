import '@testing-library/jest-dom'

import { act, fireEvent, render, screen } from '@testing-library/react'

import { SqlScatterGraphProps } from '~/queries/nodes/DataVisualization/Components/Charts/SqlScatterGraph'
import { AxisSeries } from '~/queries/nodes/DataVisualization/dataVisualizationLogic'
import { BIConfig, BIVisualizationNode } from '~/queries/schema/schema-business-intelligence'
import { NodeKind } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'
import { ChartDisplayType } from '~/types'

import { buildBIQuery, DEFAULT_BI_CONFIG } from './biEditorTypes'
import { BIScatterGraph } from './BIScatterGraph'

let mockChartProps: SqlScatterGraphProps
jest.mock('~/queries/nodes/DataVisualization/Components/Charts/SqlScatterGraph', () => ({
    SqlScatterGraph: (props: SqlScatterGraphProps) => {
        mockChartProps = props
        return <div data-testid="scatter" />
    },
}))
const config: BIConfig = {
    ...DEFAULT_BI_CONFIG,
    source: { table: 'example_orders' },
    chartType: ChartDisplayType.ScatterPlot,
    rows: [
        {
            id: 'category',
            name: 'category',
            expression: 'category',
            type: 'string',
            source: { table: 'example_orders' },
        },
    ],
    colorBy: 'category',
}
const query: BIVisualizationNode = { ...buildBIQuery(config)!.node, kind: NodeKind.BIVisualizationNode, config }
const axis = <T,>(name: string, data: T[]): AxisSeries<T> => ({
    column: { name, label: name, dataIndex: 0, type: { name: 'FLOAT', isNumerical: true } },
    data,
})
const rows = [
    ['A', 10, 20],
    ['B', 30, 40],
]
const props = {
    query,
    columns: ['category', 'x', 'y'],
    rows,
    chartKey: 'review-scatter',
    chartSettings: {},
    xData: axis('x', ['10', '30']),
    yData: [axis('y', [20, 40])],
}
const area = { x: [0, 100] as [number, number], y: [0, 100] as [number, number] }
beforeEach(() => initKeaTests())

it('selects only visible points after legend toggles and resets zoom when axes change', () => {
    const onKeepOnly = jest.fn()
    const view = render(<BIScatterGraph {...props} onKeepOnly={onKeepOnly} />)
    act(() => mockChartProps.onAreaSelect!(area))
    expect(screen.getByText('2 selected')).toBeInTheDocument()
    const hidden = mockChartProps.series!.find(({ label }) => label === 'B')!.key
    act(() => mockChartProps.legendVisibility!.onSetHiddenSeries!([hidden]))
    expect(screen.getByText('1 selected')).toBeInTheDocument()
    act(() => mockChartProps.onAreaSelect!(area))
    fireEvent.click(screen.getByText('Keep only'))
    expect(onKeepOnly).toHaveBeenCalledWith([{ category: 'A', x: 10, y: 20 }])
    fireEvent.click(screen.getByText('Select points'))
    fireEvent.click(screen.getByText('Zoom area'))
    act(() => mockChartProps.onAreaSelect!(area))
    expect(mockChartProps.viewport).toEqual(area)
    view.rerender(
        <BIScatterGraph
            {...props}
            xData={axis('y', ['20', '40'])}
            yData={[axis('x', [10, 30])]}
            onKeepOnly={onKeepOnly}
        />
    )
    expect(mockChartProps.viewport).toBeNull()
})

it('rejects excessive color cardinality before mounting the chart adapter', () => {
    const rows = Array.from({ length: 10000 }, (_, index) => [`Category ${index}`, index, index])
    render(
        <BIScatterGraph
            {...props}
            rows={rows}
            xData={axis(
                'x',
                rows.map((_, i) => String(i))
            )}
            yData={[
                axis(
                    'y',
                    rows.map((_, i) => i)
                ),
            ]}
        />
    )
    expect(screen.queryByTestId('scatter')).not.toBeInTheDocument()
    expect(screen.getByText(/Too many color groups/)).toBeInTheDocument()
})

it('handles a large selection without truncating the selected count', () => {
    const rows = Array.from({ length: 5000 }, (_, index) => [`Category ${index}`, index, index])
    render(
        <BIScatterGraph
            {...props}
            query={{ ...query, config: { ...config, colorBy: null } }}
            rows={rows}
            xData={axis(
                'x',
                rows.map((_, i) => String(i))
            )}
            yData={[
                axis(
                    'y',
                    rows.map((_, i) => i)
                ),
            ]}
            onKeepOnly={() => {}}
        />
    )
    act(() => mockChartProps.onAreaSelect!({ x: [0, 5000], y: [0, 5000] }))
    expect(screen.getByText('5000 selected')).toBeInTheDocument()
    expect(mockChartProps.series![0].points.every(({ radius }) => radius === 7)).toBe(true)
})
