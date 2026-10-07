import { BIConfig, BIField } from '~/queries/schema/schema-business-intelligence'
import { ChartDisplayType } from '~/types'

import { BI_TABLE_CALCULATIONS } from './biAnalysis'
import { BIEditorView, buildBIQuery, DEFAULT_BI_CONFIG, parseBIEditorState } from './biEditorTypes'

const field = (name: string, type: BIField['type'] = 'string'): BIField => ({
    id: name,
    name,
    expression: name,
    type,
    source: { table: 'events' },
})
const config: BIConfig = {
    ...DEFAULT_BI_CONFIG,
    source: { table: 'events' },
    rows: [{ ...field('timestamp', 'datetime'), dateBucket: 'day' }],
    columns: [field('event')],
    values: [{ field: field('properties.amount', 'float'), aggregation: 'sum' }],
}

describe('BI analysis queries', () => {
    it.each(BI_TABLE_CALCULATIONS)('persists and calculates $value before limiting results', ({ value: type }) => {
        const worksheet: BIConfig = {
            ...config,
            values: [{ ...config.values[0], tableCalculation: { type, window: 7 } }],
        }
        const parsed = parseBIEditorState(BIEditorView.BI, JSON.stringify(worksheet))!.config
        expect(parsed.values[0].tableCalculation).toEqual({ type, window: 7 })
        const result = buildBIQuery(parsed)!
        expect(result.query).toMatch(new RegExp(`LIMIT ${worksheet.limit}$`))
        expect(buildBIQuery(parsed, true)!.query).toMatch(new RegExp(`LIMIT ${worksheet.limit + 1}$`))
        expect(result.query).toContain('OVER (PARTITION BY bi_column_event')
        expect(result.query.match(/LIMIT/g)).toHaveLength(1)
        if (type === 'percent_change' || type === 'percent_of_total') {
            expect(result.query).toContain('nullIf(')
            expect(result.node.tableSettings?.columns?.map((column) => column.column)).toEqual([
                'bi_row_timestamp',
                'bi_column_event',
                'sum_properties_amount',
            ])
            expect(result.node.tableSettings?.columns?.[2].settings?.formatting?.style).toBe('percent')
        }
        if (type === 'moving_average') {
            expect(result.query).toContain('6 PRECEDING AND CURRENT ROW')
        }
        if (type === 'running_total') {
            expect(result.query).toContain('ORDER BY bi_row_timestamp ASC ROWS')
        }
        const across = buildBIQuery({
            ...worksheet,
            values: [{ ...worksheet.values[0], tableCalculation: { type, computeUsing: 'table' } }],
        })!
        expect(across.query).not.toContain('PARTITION BY bi_column_event')
    })

    it.each(['average', 'count_distinct'] as const)('reaggregates %s for Other and totals', (aggregation) => {
        const worksheet: BIConfig = {
            ...config,
            chartType: ChartDisplayType.TwoDimensionalHeatmap,
            values: [{ field: field('properties.amount', 'float'), aggregation }],
            topN: { fieldId: 'event', count: 5, measureIndex: 0, includeOther: true },
            totals: { rows: true, columns: true, subtotals: true },
        }
        const result = buildBIQuery(worksheet)!
        expect(result.query).toContain('GROUP BY bi_key ORDER BY')
        expect(result.query).toContain(
            'GROUPING SETS ((bi_row_timestamp, bi_column_event), (bi_row_timestamp), (bi_column_event), ())'
        )
        expect(result.query).toContain("['1', 'Other']")
        expect(result.query).toContain("' (category)'")
        expect(result.query).not.toMatch(/sum\((average|count_distinct)/)
        expect(result.query).toContain('grouping(bi_row_timestamp, bi_column_event)')
        expect(parseBIEditorState(BIEditorView.BI, worksheet)?.config.topN).toEqual(worksheet.topN)
        expect(parseBIEditorState(BIEditorView.BI, worksheet)?.config.totals).toEqual(worksheet.totals)
    })

    it('reserves detail rows and sorts numeric dimensions before their total labels are formatted', () => {
        const result = buildBIQuery({
            ...config,
            chartType: ChartDisplayType.ActionsTable,
            limit: 100,
            rows: [field('number', 'integer')],
            totals: { rows: true, columns: true },
            sort: { key: 'rows:number', direction: 'asc' },
        })!
        expect(result.query).toContain('PARTITION BY bi_grouping = 0')
        expect(result.query).toContain('GROUPING SETS ((bi_row_number, bi_column_event), ())')
        expect(result.query).toContain('WHERE bi_grouping = 0 OR bi_rank <= 50')
        expect(result.query).toContain('ORDER BY bi_grouping DESC, bi_result.bi_row_number ASC LIMIT 100')
        const probe = buildBIQuery(
            { ...config, chartType: ChartDisplayType.ActionsTable, limit: 100, totals: { rows: true } },
            true
        )!
        expect(probe.query).toContain('WHERE bi_grouping = 0 OR bi_rank <= 50')
        expect(probe.query).toMatch(/LIMIT 101$/)
    })

    it('probes beyond the combined comparison limit without changing the saved query', () => {
        const worksheet: BIConfig = {
            ...config,
            limit: 100,
            dateRange: { date_from: '-7d' },
            compareFilter: { compare: true },
        }
        const saved = buildBIQuery(worksheet)!
        const probe = buildBIQuery(worksheet, true)!
        expect(saved.query).toMatch(/^SELECT \* FROM \(/)
        expect(saved.query).toMatch(/\)\) LIMIT 100$/)
        expect(probe.query).toContain('UNION ALL')
        expect(probe.query.match(/LIMIT 101/g)).toHaveLength(3)
        expect(probe.query).toMatch(/\)\) LIMIT 101$/)
    })

    it.each([undefined, '-1y'])(
        'keeps period windows independent and shares the current-period Top N (%s)',
        (compare_to) => {
            const result = buildBIQuery({
                ...config,
                dateRange: { date_from: '-7d' },
                compareFilter: { compare: true, compare_to },
                topN: { fieldId: 'event', count: 5, measureIndex: 0, includeOther: false },
                values: [{ ...config.values[0], tableCalculation: { type: 'running_total' } }],
            })!
            expect(result.query).toContain('{filters.previous}')
            expect(result.query).toContain('{filters.compareDate(timestamp)}')
            expect(result.query).toContain('FROM bi_previous')
            expect(result.query.match(/FROM bi_top/g)).toHaveLength(4)
            expect(result.query).toContain(`'${compare_to ? 'Comparison period' : 'Previous period'}' AS bi_period`)
        }
    )

    it.each([
        { topN: { fieldId: 'event', count: -1, measureIndex: 0, includeOther: true } },
        { totals: { rows: 'true' } },
        {
            values: [
                { ...config.values[0], tableCalculation: { type: 'moving_average', window: '7); DROP TABLE events' } },
            ],
        },
    ])('rejects malformed analysis settings %j', (invalid) => {
        expect(parseBIEditorState(BIEditorView.BI, { ...config, ...invalid })).toBeNull()
    })
})
