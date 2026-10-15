import { BIConfig, BIField } from '~/queries/schema/schema-business-intelligence'
import { ChartDisplayType } from '~/types'

import { getBIDrillSelection } from './biDrilldown'
import { DEFAULT_BI_CONFIG } from './biEditorTypes'
import { biPivotCellKey, buildBIPivotModel, visibleBIPivotMembers } from './biPivot'

const field = (name: string): BIField => ({
    id: name,
    name,
    expression: name,
    type: 'string',
    source: { table: 'events' },
})

it('keeps reaggregated multi-measure hierarchy cells and their drill-down dimensions when collapsed', () => {
    const config: BIConfig = {
        ...DEFAULT_BI_CONFIG,
        source: { table: 'events' },
        chartType: ChartDisplayType.TwoDimensionalHeatmap,
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
    expect(collapsed.map((row) => row.label)).toEqual(['Europe', 'Total (category)', '(empty)', 'Total'])
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
})
