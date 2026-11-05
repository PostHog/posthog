import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react'

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
afterEach(cleanup)

it('selects only visible points after legend toggles and resets zoom when axes change', () => {
    const onKeepOnly = jest.fn()
    const view = render(<BIScatterGraph {...props} onKeepOnly={onKeepOnly} />)
    const originalSeries = mockChartProps.series
    act(() => mockChartProps.onAreaSelect!(area))
    expect(mockChartProps.series).toBe(originalSeries)
    expect(screen.getByTestId('bi-scatter-selection-count')).toHaveTextContent('2 selected')
    const hidden = mockChartProps.series!.find(({ label }) => label === 'B')!.key
    act(() => mockChartProps.legendVisibility!.onSetHiddenSeries!([hidden]))
    expect(screen.getByTestId('bi-scatter-selection-count')).toHaveTextContent('1 selected')
    act(() => mockChartProps.onAreaSelect!(area))
    fireEvent.click(screen.getByText('Keep only'))
    expect(onKeepOnly).toHaveBeenCalledWith([{ category: 'A', x: 10, y: 20 }])
    fireEvent.click(within(screen.getByTestId('bi-scatter-selection')).getByText('Select points'))
    fireEvent.click(screen.getByText('Zoom area'))
    act(() => mockChartProps.onAreaSelect!(area))
    expect(mockChartProps.viewport).toEqual(area)
    view.rerender(
        <BIScatterGraph
            {...props}
            yData={[{ ...props.yData[0], settings: { formatting: { style: 'percent' } } }]}
            onKeepOnly={onKeepOnly}
        />
    )
    expect(mockChartProps.viewport).toBeNull()
    fireEvent.click(within(screen.getByTestId('bi-scatter-selection')).getByText('Select points'))
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

it.each([
    { count: 10000, measures: 1, colorBy: 'category' },
    { count: 500, measures: 50, colorBy: null },
])('rejects $count rows with $measures measures before allocating point labels', ({ count, measures, colorBy }) => {
    let memberReads = 0
    const rows = Array.from({ length: count }, (_, index) =>
        Object.defineProperty([`Category ${index}`, index, index], 0, {
            get: () => {
                memberReads++
                return `Category ${index}`
            },
        })
    )
    render(
        <BIScatterGraph
            {...props}
            query={{ ...query, config: { ...config, colorBy } }}
            rows={rows}
            xData={axis(
                'x',
                rows.map((_, i) => String(i))
            )}
            yData={Array.from({ length: measures }, (_, index) =>
                axis(
                    `y-${index}`,
                    rows.map((_, i) => i)
                )
            )}
        />
    )
    expect(screen.queryByTestId('scatter')).not.toBeInTheDocument()
    expect(screen.getByText(/Too many color groups/)).toBeInTheDocument()
    expect(memberReads).toBeLessThan(1000)
})

it('reuses row identities and allocates records only within the selection limit', () => {
    let extraReads = 0
    let dimensionReads = 0
    const onKeepOnly = jest.fn()
    const rows = Array.from({ length: 5000 }, (_, index) =>
        Object.defineProperties([`Category ${index}`, index, index], {
            0: {
                get: () => {
                    dimensionReads++
                    return `Category ${index}`
                },
            },
            3: {
                get: () => {
                    extraReads++
                    return 'Example extra value'
                },
            },
        })
    )
    render(
        <BIScatterGraph
            {...props}
            query={{ ...query, config: { ...config, colorBy: null } }}
            rows={rows}
            columns={['category', 'x', 'y', 'extra']}
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
            onKeepOnly={onKeepOnly}
        />
    )
    const readsBeforeSelection = extraReads
    const identitiesBeforeSelection = dimensionReads
    act(() => mockChartProps.onAreaSelect!({ x: [0, 5000], y: [0, 5000] }))
    expect(screen.getByTestId('bi-scatter-selection-count')).toHaveTextContent('5000 selected')
    expect(extraReads).toBe(readsBeforeSelection)
    expect(dimensionReads).toBe(identitiesBeforeSelection)
    expect(screen.getByText('Keep only').closest('button')).toHaveAttribute('aria-disabled', 'true')
    expect(mockChartProps.series![0].points.every((point) => mockChartProps.isPointHighlighted!(point))).toBe(true)
    act(() => mockChartProps.onAreaSelect!({ x: [0, 2], y: [0, 2] }))
    expect(screen.getByTestId('bi-scatter-selection-count')).toHaveTextContent('3 selected')
    fireEvent.click(screen.getByText('Keep only'))
    expect(onKeepOnly.mock.calls[0][0]).toHaveLength(3)
    expect(onKeepOnly.mock.calls[0][0][0]).toMatchObject({ extra: 'Example extra value' })
    const readsBeforeToggle = dimensionReads
    const firstSeries = mockChartProps.series![0]
    act(() =>
        mockChartProps.onPointClick!({
            ...firstSeries.points[4],
            seriesKey: firstSeries.key,
            seriesLabel: firstSeries.label,
            seriesIndex: 0,
            pointIndex: 4,
            color: '#000000',
        })
    )
    expect(screen.getByTestId('bi-scatter-selection-count')).toHaveTextContent('1 selected')
    expect(dimensionReads - readsBeforeToggle).toBe(1)
})
