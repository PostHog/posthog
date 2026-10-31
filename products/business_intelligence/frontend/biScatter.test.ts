import { AxisSeries } from '~/queries/nodes/DataVisualization/dataVisualizationLogic'
import { BIConfig, BIField, BIVisualizationNode } from '~/queries/schema/schema-business-intelligence'
import { NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import {
    buildBIQuery,
    DEFAULT_BI_CONFIG,
    getBIResultDimensions,
    getBIResultMeasureColumns,
    mergeBIChartSettings,
} from './biEditorTypes'
import { buildBIConditionExpression } from './biFilterGroups'
import { buildBIScatterSeries, getBIScatterRowKey, keepBIScatterRows } from './biScatter'

const field = (name: string, type: BIField['type'] = 'string'): BIField => ({
    id: name,
    name,
    expression: name,
    type,
    source: { table: 'example_orders' },
})
const item = field('item')
const segment = field('segment')
const config: BIConfig = {
    ...DEFAULT_BI_CONFIG,
    source: item.source,
    chartType: ChartDisplayType.ScatterPlot,
    rows: [item, segment],
    values: [
        { field: field('revenue', 'float'), aggregation: 'sum' },
        { field: field('cost', 'float'), aggregation: 'sum' },
    ],
}
const axis = <T>(name: string, data: T[]): AxisSeries<T> => ({
    column: { name, label: name, dataIndex: 0, type: { name: 'FLOAT', isNumerical: true } },
    data,
})
const node = (config: BIConfig): BIVisualizationNode => ({
    ...buildBIQuery(config)!.node,
    kind: NodeKind.BIVisualizationNode,
    config,
})

it('keeps measures on numeric axes as detail dimensions are added, including numeric identifiers', () => {
    const aggregate = node({ ...config, rows: [] })
    const detail = node({ ...config, rows: [field('item_id', 'integer'), segment] })
    expect(detail.chartSettings?.xAxis).toEqual(aggregate.chartSettings?.xAxis)
    expect(detail.chartSettings?.yAxis).toEqual(aggregate.chartSettings?.yAxis)
    expect(detail.source.query).toContain('GROUP BY')
    expect(aggregate.source.query).not.toContain('GROUP BY')
    const swapped = {
        ...aggregate.chartSettings,
        xAxis: aggregate.chartSettings!.yAxis![0],
        yAxis: [aggregate.chartSettings!.xAxis!],
        xAxisLabel: 'My cost label',
    }
    expect(mergeBIChartSettings(swapped, detail.chartSettings, aggregate.chartSettings, true)).toMatchObject(swapped)
    expect(
        mergeBIChartSettings({ xAxis: { column: 'deleted' } }, detail.chartSettings, undefined, true)?.xAxis
    ).toEqual(detail.chartSettings?.xAxis)
})

it('keeps coincident members distinct and category colors stable across order, aliases and single-color mode', () => {
    const dimensions = getBIResultDimensions(config).map(({ column }) => column)
    const measures = getBIResultMeasureColumns(config).map(({ column }) => column)
    const columns = [...dimensions, ...measures]
    const rows = [
        ['A', 'North', 10, 4],
        ['B', 'South', 10, 4],
        ['C', null, 20, 7],
        ['D', '', 30, 9],
    ]
    const colored = node({
        ...config,
        colorBy: segment.id,
        memberAliases: [
            {
                field: segment,
                aliases: [
                    { value: 'North', label: 'Same' },
                    { value: 'South', label: 'Same' },
                ],
            },
        ],
    })
    const build = (
        query: BIVisualizationNode,
        rows: unknown[][]
    ): NonNullable<ReturnType<typeof buildBIScatterSeries>> =>
        buildBIScatterSeries(
            query,
            columns,
            rows,
            axis(
                measures[0],
                rows.map((row) => String(row[2]))
            ),
            [
                axis(
                    measures[1],
                    rows.map((row) => Number(row[3]))
                ),
            ]
        )!
    const series = build(colored, rows)
    expect(series).toHaveLength(4)
    expect(series.filter((series) => series.label === 'Same')).toHaveLength(2)
    expect(new Set(series.flatMap((series) => series.points.map((point) => point.meta?.rowKey))).size).toBe(4)
    expect(build(colored, [...rows].reverse()).map(({ key, color }) => ({ key, color }))).toEqual(
        series.map(({ key, color }) => ({ key, color }))
    )
    expect(getBIScatterRowKey(config, columns, rows[0])).not.toEqual(getBIScatterRowKey(config, columns, rows[1]))
    expect(new Set(build(node({ ...config, colorBy: null }), rows).map(({ color }) => color)).size).toBe(1)
})

it('omits missing/non-numeric coordinates while retaining zero and negative values', () => {
    const series = buildBIScatterSeries(
        node(config),
        ['item', 'segment'],
        [
            ['A', 'X'],
            ['B', 'X'],
            ['C', 'X'],
            ['D', 'X'],
            ['E', 'X'],
        ],
        axis('x', ['', 'bad', '0', '-2', '4']),
        [axis('y', [1, 2, 3, -4, null])]
    )
    expect(series!.flatMap(({ points }) => points.map(({ x, y }) => [x, y]))).toEqual([
        [0, 3],
        [-2, -4],
    ])
})

it('keeps exact selected tuples AND existing OR restrictions, including null and empty members', () => {
    const original: BIConfig = {
        ...config,
        filters: [
            { field: field('market'), operator: 'equals', value: 'retail' },
            { field: field('channel'), operator: 'equals', value: 'direct' },
        ],
        rowFilterGroup: { operator: 'OR', filters: ['market', 'channel'], groups: [] },
    }
    const [itemColumn, segmentColumn] = getBIResultDimensions(original).map(({ column }) => column)
    const selected = keepBIScatterRows(original, [
        { [itemColumn]: 'A', [segmentColumn]: 'X' },
        { [itemColumn]: 'B', [segmentColumn]: 'Y' },
        { [itemColumn]: null, [segmentColumn]: '' },
    ])!
    const evaluate = (record: Record<string, unknown>): boolean => {
        const expressions = new Map(
            selected.filters.map((filter) => [
                filter.field.id,
                String(
                    filter.operator === 'is_not_set'
                        ? record[filter.field.expression] === null
                        : record[filter.field.expression] === (filter.values?.[0] ?? filter.value)
                ),
            ])
        )
        const expression = buildBIConditionExpression(selected.rowFilterGroup!, expressions)!
        // Evaluate the small boolean tree without executing generated code.
        const evaluateGroup = (group: NonNullable<BIConfig['rowFilterGroup']>): boolean => {
            const values = [
                ...group.filters.map((id) => expressions.get(id) === 'true'),
                ...group.groups.map(evaluateGroup),
            ]
            return group.operator === 'AND' ? values.every(Boolean) : values.some(Boolean)
        }
        expect(expression).toContain('OR')
        return evaluateGroup(selected.rowFilterGroup!)
    }
    expect(evaluate({ item: 'A', segment: 'X', market: 'retail' })).toBe(true)
    expect(evaluate({ item: 'B', segment: 'Y', channel: 'direct' })).toBe(true)
    expect(evaluate({ item: 'A', segment: 'Y', market: 'retail' })).toBe(false)
    expect(evaluate({ item: 'A', segment: 'X', market: 'wholesale' })).toBe(false)
    expect(evaluate({ item: null, segment: '', channel: 'direct' })).toBe(true)
    expect(buildBIQuery(selected)?.query).toContain('IS NULL')
    expect(original.filters).toHaveLength(2)
    for (const unsupported of [undefined, ['X'], { value: 'X' }, NaN]) {
        expect(keepBIScatterRows(config, [{ [itemColumn]: 'A', [segmentColumn]: unsupported }])).toBeNull()
    }
    expect(keepBIScatterRows(config, [])).toBeNull()
    expect(keepBIScatterRows(config, Array(201).fill({ [itemColumn]: 'A' }))).toBeNull()
})

it.each(['month', 'quarter', 'day_of_week'] as const)(
    'keeps numeric %s members without converting them to dates',
    (datePart) => {
        const worksheet: BIConfig = {
            ...config,
            rows: [],
            columns: [{ ...field('placed_at', 'date'), datePart }],
            values: [config.values[0]],
        }
        const column = getBIResultDimensions(worksheet)[0].column
        const selected = keepBIScatterRows(worksheet, [{ [column]: 2 }, { [column]: 3 }])!
        expect(selected.filters.map(({ value }) => value)).toEqual(['2', '3'])
        const sql = buildBIQuery(selected)!.query
        expect(sql).toContain(`${column} = 2`)
        expect(sql).toContain(`${column} = 3`)
        expect(sql).not.toContain('1970-01-01')
        expect(buildBIQuery({ ...selected, filters: [{ ...selected.filters[0], value: 'not a number' }] })).toBeNull()
    }
)
