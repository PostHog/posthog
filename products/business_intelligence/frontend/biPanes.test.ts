import { buildSeries, getSeriesKey } from '~/queries/nodes/DataVisualization/Components/Charts/sqlLineGraphAdapter'
import { resolveSQLReferenceLines } from '~/queries/nodes/DataVisualization/Components/Charts/sqlReferenceLines'
import { Column } from '~/queries/nodes/DataVisualization/dataVisualizationLogic'
import { BIConfig, BIField } from '~/queries/schema/schema-business-intelligence'
import { GoalLine } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import {
    BIEditorView,
    buildBIQuery,
    DEFAULT_BI_CONFIG,
    getBIChartFit,
    getBIResultDimensions,
    getBIResultMeasureColumns,
    normalizeBIConfig,
    parseBIEditorState,
} from './biEditorTypes'
import { buildBIPanes, MAX_BI_PANES } from './biPanes'

const field = (name: string): BIField => ({
    id: name,
    name,
    expression: name,
    type: 'string',
    source: { table: 'example_orders' },
})
const region = field('region')
const category = field('category')
const channel = field('channel')
const config: BIConfig = {
    ...DEFAULT_BI_CONFIG,
    source: region.source,
    chartType: ChartDisplayType.ActionsBar,
    rows: [region],
    columns: [category, channel],
    colorBy: channel.id,
    panes: { fields: [region.id] },
    values: [{ field: { ...field('revenue'), type: 'float' }, aggregation: 'sum' }],
}
const columnsFor = (config: BIConfig): Column[] =>
    [
        ...getBIResultDimensions(config).map(({ column }) => column),
        ...getBIResultMeasureColumns(config).map(({ column }) => column),
    ].map((name, dataIndex) => ({ name, label: name, dataIndex, type: { name: 'STRING', isNumerical: false } }))
const columns = columnsFor(config)
const rows = [
    ['North', 'A', 'direct', 10],
    ['North', 'B', 'partner', 20],
    ['South', 'A', 'partner', 40],
]
const mean: GoalLine = { label: 'Average', value: 0, calculation: 'mean', scope: 'all' }

it('keeps category and color independent inside panes, including missing cells and drill-down tuples', () => {
    const model = buildBIPanes(config, {}, columns, rows, [mean])
    expect(model.error).toBeUndefined()
    expect(model.panes.map((pane) => pane.title)).toEqual(['region: North', 'region: South'])
    expect(model.panes[0].yData.map((series) => series.data)).toEqual([
        [10, null],
        [null, 20],
    ])
    expect(model.panes[1].yData.map((series) => series.data)).toEqual([
        [null, null],
        [40, null],
    ])
    expect(model.valueDomain).toEqual({ min: 0, max: 40 })
    expect(
        model.panes.map(
            (pane) => resolveSQLReferenceLines(pane.goalLines, buildSeries(pane.yData, config.chartType))[0].value
        )
    ).toEqual([15, 40])
    const pane = model.panes[1]
    expect(pane.records.get(JSON.stringify([getSeriesKey(pane.yData[1], 1), 0]))).toEqual(
        Object.fromEntries(columns.map((column) => [column.name, rows[2][column.dataIndex]]))
    )
    const reordered = buildBIPanes(config, {}, columns, [...rows].reverse())
    expect(reordered.panes[0].yData.map((series) => series.settings?.display?.color)).toEqual(
        pane.yData.map((series) => series.settings?.display?.color)
    )
})

it('keeps null, empty strings and colliding aliases distinct', () => {
    const aliased = {
        ...config,
        memberAliases: [
            {
                field: region,
                aliases: [
                    { value: null, label: 'Same label' },
                    { value: '', label: 'Same label' },
                ],
            },
        ],
    }
    const model = buildBIPanes(aliased, {}, columns, [
        [null, 'A', 'direct', 1],
        ['', 'A', 'direct', 2],
    ])
    expect(model.panes).toHaveLength(2)
    expect(new Set(model.panes.map((pane) => pane.key)).size).toBe(2)
    expect(model.panes[0].title).toEqual(model.panes[1].title)
})

it('bounds the pane count while worksheet reference lines include all returned marks', () => {
    const data = Array.from({ length: MAX_BI_PANES + 1 }, (_, index) => [`Region ${index}`, 'A', 'direct', index])
    const model = buildBIPanes(
        { ...config, panes: { fields: [region.id], referenceLines: 'worksheet' } },
        {},
        columns,
        data,
        [mean]
    )
    expect(model.panes).toHaveLength(MAX_BI_PANES)
    expect(model.warnings[0]).toContain('24 of 25 panes')
    expect(
        model.panes.every((pane) => pane.goalLines[0].value === 12 && pane.goalLines[0].calculation === 'fixed')
    ).toBe(true)
})

it.each([false, true])('uses plotted null handling for worksheet reference lines (zero: %s)', (showNullsAsZero) => {
    const model = buildBIPanes(
        { ...config, panes: { fields: [region.id], referenceLines: 'worksheet' } },
        { showNullsAsZero },
        columns,
        [
            ['North', 'A', 'direct', 10],
            ['South', 'A', 'direct', null],
        ],
        [mean]
    )
    expect(model.panes.map((pane) => pane.goalLines[0].value)).toEqual(showNullsAsZero ? [5, 5] : [10, 10])
})

it('uses plotted percentage units and keeps independent and percent-stack scales automatic', () => {
    const settings = {
        yAxis: [
            {
                column: getBIResultMeasureColumns(config)[0].column,
                settings: { formatting: { style: 'percent' as const } },
            },
        ],
    }
    const model = buildBIPanes(config, settings, columns, [['North', 'A', 'direct', 0.25]])
    expect(model.panes[0].yData[0].data).toEqual([25])
    expect(model.valueDomain).toEqual({ min: 0, max: 25 })
    expect(
        buildBIPanes({ ...config, panes: { fields: [region.id], independentAxes: true } }, {}, columns, rows)
            .valueDomain
    ).toBeUndefined()
    expect(
        buildBIPanes(
            { ...config, chartType: ChartDisplayType.ActionsStackedBar },
            { stackBars100: true },
            columns,
            rows
        ).valueDomain
    ).toBeUndefined()
})

it('includes stacked extents and fixed reference lines in the shared scale', () => {
    const model = buildBIPanes(
        { ...config, chartType: ChartDisplayType.ActionsStackedBar },
        {},
        columns,
        [
            ['North', 'A', 'direct', 10],
            ['North', 'A', 'partner', 20],
        ],
        [{ label: 'Target', value: 50 }]
    )
    expect(model.valueDomain).toEqual({ min: 0, max: 50 })
    expect(
        buildBIPanes({ ...config, chartType: ChartDisplayType.ActionsStackedBar }, {}, columns, [
            ['North', 'A', 'direct', 10],
            ['North', 'A', 'partner', 20],
        ]).valueDomain
    ).toEqual({ min: 0, max: 30 })
})

it('preserves pane and color settings through serialization, and prunes removed dimensions', () => {
    expect(
        parseBIEditorState(BIEditorView.BI, JSON.stringify({ ...config, panes: null }))?.config.panes
    ).toBeUndefined()
    expect(
        parseBIEditorState(
            BIEditorView.BI,
            JSON.stringify({
                ...config,
                panes: { fields: [region.id], independentAxes: null, referenceLines: null },
            })
        )?.config.panes
    ).toEqual({ fields: [region.id] })
    expect(parseBIEditorState(BIEditorView.BI, JSON.stringify(config))?.config).toMatchObject({
        panes: config.panes,
        colorBy: channel.id,
    })
    expect(getBIChartFit(config, ChartDisplayType.ActionsBar).fits).toBe(true)
    expect(getBIChartFit(config, ChartDisplayType.ActionsPie).fits).toBe(false)
    const query = buildBIQuery(config)!
    expect(query.query).toContain('GROUP BY')
    expect(getBIResultDimensions(config)).toHaveLength(3)
    expect(query.node.chartSettings?.xAxis?.column).toBe(getBIResultDimensions(config)[1].column)
    expect(normalizeBIConfig({ ...config, rows: [] }).panes).toBeUndefined()
    expect(buildBIPanes(config, {}, columns, [...rows, rows[0]]).error).toContain('More than one result group')
    expect(buildBIPanes(config, {}, columns.slice(1), rows).error).toContain('returned columns')
    expect(buildBIPanes({ ...config, columns: [channel] }, {}, columns, rows).error).toContain('axis dimension')
})

it('orders nested pane dimensions independently of the shelves and sorts quarter marks within each pane', () => {
    const year: BIField = { ...field('Order date'), id: 'year', type: 'datetime', dateBucket: 'year' }
    const quarter: BIField = { ...year, id: 'quarter', dateBucket: undefined, datePart: 'quarter' }
    const nested: BIConfig = {
        ...config,
        rows: [year, region],
        columns: [quarter, channel],
        panes: { fields: [region.id, year.id] },
    }
    const model = buildBIPanes(
        nested,
        {},
        columnsFor(nested),
        [
            ['2025-01-01', 'North', 4, 'direct', 40],
            ['2025-01-01', 'North', 1, 'direct', 10],
            ['2024-01-01', 'North', 1, 'partner', 20],
        ],
        [{ ...mean, scope: 'series' }]
    )
    expect(model.error).toBeUndefined()
    expect(model.panes.map((pane) => pane.title)).toEqual([
        'region: North › YEAR(Order date): 2025',
        'region: North › YEAR(Order date): 2024',
    ])
    expect([...model.labels.values()]).toEqual(['Q1', 'Q4'])
    expect(model.panes[0].yData[0].data).toEqual([10, 40])
    expect(
        resolveSQLReferenceLines(model.panes[0].goalLines, buildSeries(model.panes[0].yData, nested.chartType))
    ).toMatchObject([{ value: 25 }])
})
