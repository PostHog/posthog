import { BIConfig, BIField } from '~/queries/schema/schema-business-intelligence'
import { NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { getBIDrillSelection } from './biDrilldown'
import { buildBIQuery, getBIResultDimensions, DEFAULT_BI_CONFIG } from './biEditorTypes'
import { biPivotCellKey, buildBIPivotModel, visibleBIPivotMembers } from './biPivot'
import { isBIPivotTable } from './biTableLayout'

const field = (name: string): BIField => ({
    id: name,
    name,
    expression: name,
    type: 'string',
    source: { table: 'events' },
})

it.each([ChartDisplayType.TwoDimensionalHeatmap, ChartDisplayType.ActionsTable])(
    'keeps reaggregated multi-measure hierarchy cells and their drill-down dimensions in %s when collapsed',
    (chartType) => {
        const config: BIConfig = {
            ...DEFAULT_BI_CONFIG,
            source: { table: 'events' },
            chartType,
            rows: [field('region'), field('city')],
            columns: [field('year'), field('quarter')],
            totals: { rows: true, columns: true },
            values: [
                { field: field('amount'), aggregation: 'average' },
                { field: field('user'), aggregation: 'count_distinct' },
            ],
        }
        const model = buildBIPivotModel(
            config,
            ['bi_rows', 'bi_columns', 'average_amount', 'count_distinct_user_2'],
            [
                ['["Europe","Total"]', '["2026","Total"]', 17.5, 3],
                ['["Europe","Paris"]', '["2026","Q1"]', 10, 2],
                ['["Europe","Rome"]', '["2026","Q1"]', 20, 2],
                ['["Total","Total"]', '["Total","Total"]', 17.5, 3],
                ['["Total (category)",null]', '["2026","Q1"]', 8, 1],
            ]
        )
        const collapsed = visibleBIPivotMembers(model.rows, new Set(['["Europe"]']), true)
        expect(collapsed.map((row) => row.label)).toEqual(['Europe', 'Total (category)', '(no value)', 'Total'])
        expect(visibleBIPivotMembers(model.columns, new Set(['["2026"]']), false).map((row) => row.label)).toEqual([
            '2026',
            'Total',
        ])
        const record = model.cells.get(biPivotCellKey(['Europe'], ['2026']))!
        expect(record.average_amount).toBe(17.5)
        expect(record.count_distinct_user_2).toBe(3)
        expect(getBIDrillSelection(config, record).filters.map(({ field, value }) => [field.name, value])).toEqual([
            ['region', 'Europe'],
            ['year', '2026'],
        ])
        const empty = model.cells.get(biPivotCellKey(['Total (category)', null], ['2026', 'Q1']))!
        expect(getBIDrillSelection(config, empty).filters.map(({ operator, value }) => [operator, value])).toEqual([
            ['equals', 'Total'],
            ['is_not_set', ''],
            ['equals', '2026'],
            ['equals', 'Q1'],
        ])
    }
)

it('pivots table members by shelf and restores flat results when dimensions return to rows', () => {
    const region = field('region')
    const channel = field('channel')
    const config: BIConfig = {
        ...DEFAULT_BI_CONFIG,
        source: region.source,
        chartType: ChartDisplayType.ActionsTable,
        rows: [region],
        columns: [channel],
        values: [
            { field: field('amount'), aggregation: 'sum' },
            { field: field('orders'), aggregation: 'count' },
        ],
    }
    const results = [
        ['north', 'direct', 12, 3],
        ['north', 'partner', 8, 2],
        ['south', 'direct', 9, 1],
    ]
    const columns = [...getBIResultDimensions(config).map(({ column }) => column), 'sum_amount', 'count_orders_2']
    const model = buildBIPivotModel(config, columns, results)
    expect(isBIPivotTable(config)).toBe(true)
    expect(model.rows.map(({ label }) => label)).toEqual(['north', 'south'])
    expect(model.columns.map(({ label }) => label)).toEqual(['direct', 'partner'])
    expect(model.cells.get(biPivotCellKey(['north'], ['partner']))).toMatchObject({ sum_amount: 8, count_orders_2: 2 })
    expect(model.cells.has(biPivotCellKey(['south'], ['partner']))).toBe(false)
    const swapped = { ...config, rows: [channel], columns: [region] }
    const transposed = buildBIPivotModel(
        swapped,
        [...getBIResultDimensions(swapped).map(({ column }) => column), 'sum_amount', 'count_orders_2'],
        results.map(([region, channel, ...values]) => [channel, region, ...values])
    )
    expect(transposed.rows.map(({ label }) => label)).toEqual(['direct', 'partner'])
    expect(transposed.columns.map(({ label }) => label)).toEqual(['north', 'south'])
    expect(transposed.cells.get(biPivotCellKey(['partner'], ['north']))).toMatchObject({
        sum_amount: 8,
        count_orders_2: 2,
    })
    const flat = { ...config, rows: [region, channel], columns: [] }
    expect(isBIPivotTable(flat)).toBe(false)
    expect(getBIResultDimensions(flat).map(({ column }) => column)).toEqual(['region', 'channel'])
    expect(buildBIQuery(flat)?.query).not.toContain('bi_current')

    const columnsOnly = { ...config, rows: [], columns: [region] }
    const columnResults = [
        ['north', 20, 5],
        ['south', 9, 1],
    ]
    const horizontal = buildBIPivotModel(
        columnsOnly,
        [...getBIResultDimensions(columnsOnly).map(({ column }) => column), 'sum_amount', 'count_orders_2'],
        columnResults
    )
    expect(isBIPivotTable(columnsOnly)).toBe(true)
    expect(horizontal.rows.map(({ path, label }) => ({ path, label }))).toEqual([{ path: [], label: '' }])
    expect(horizontal.columns.map(({ label }) => label)).toEqual(['north', 'south'])
    const north = horizontal.cells.get(biPivotCellKey([], ['north']))!
    expect(north).toMatchObject({ sum_amount: 20, count_orders_2: 5 })
    expect(getBIDrillSelection(columnsOnly, north).filters.map(({ field, value }) => [field.name, value])).toEqual([
        ['region', 'north'],
    ])
    expect(buildBIPivotModel(columnsOnly, [], []).rows).toEqual([])
})

it.each([
    { chartType: ChartDisplayType.ActionsLineGraph },
    { columns: [] },
    { columns: [field('   ')] },
    { compareFilter: { compare: true } },
    { source: { table: 'orders', connectionId: 'example-connection' } },
    { querySnapshot: { kind: NodeKind.HogQLQuery, query: 'SELECT 1' } },
] satisfies Partial<BIConfig>[])('keeps non-pivot presentations for %j', (overrides) => {
    expect(
        isBIPivotTable({
            ...DEFAULT_BI_CONFIG,
            chartType: ChartDisplayType.ActionsTable,
            rows: [field('region')],
            columns: [field('channel')],
            ...overrides,
        })
    ).toBe(false)
})
