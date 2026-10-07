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
    it.each(['gap', 'zero'] as const)(
        'fills %s date buckets separately in each period before window calculations',
        (missingDates) => {
            const worksheet: BIConfig = {
                ...config,
                chartType: ChartDisplayType.ActionsLineGraph,
                missingDates,
                dateRange: { date_from: '-7d' },
                compareFilter: { compare: true },
                values: [
                    {
                        ...config.values[0],
                        tableCalculation: { type: 'moving_average', window: 3, requireFullWindow: true },
                    },
                ],
            }
            const parsed = parseBIEditorState(BIEditorView.BI, worksheet)!.config
            expect(parsed.missingDates).toBe(missingDates)
            expect(parsed.values[0].tableCalculation?.requireFullWindow).toBe(true)
            const query = buildBIQuery(parsed)!.query
            expect(query).toContain('bi_current_filled AS')
            expect(query).toContain('bi_previous_filled AS')
            expect(query).toContain('FROM toStartOfDay({filters.dateRange.from})')
            expect(query).toContain('ORDER BY bi_column_event ASC, bi_row_timestamp ASC WITH FILL')
            expect(query).toContain('2 PRECEDING AND CURRENT ROW) = 3')
            expect(query.indexOf('bi_current_filled AS')).toBeLessThan(query.indexOf('bi_calculated AS'))
            expect(query.includes('INTERPOLATE (sum_properties_amount AS 0)')).toBe(missingDates === 'zero')
            expect(buildBIQuery({ ...worksheet, dateRange: { date_from: 'all' } })!.query).not.toContain('WITH FILL')
        }
    )
    it.each([false, true])(
        'filters aggregated and calculated results before the final limit (comparison: %s)',
        (compare) => {
            const worksheet: BIConfig = {
                ...config,
                dateRange: { date_from: '-7d' },
                compareFilter: { compare },
                values: [
                    config.values[0],
                    { field: field('event'), aggregation: 'count' },
                    {
                        field: field('calculation', 'float'),
                        aggregation: 'custom',
                        customExpression: 'sum(properties.amount) / count(*)',
                        label: 'Revenue per purchase',
                        tableCalculation: { type: 'running_total' },
                    },
                ],
                resultFilters: [
                    { id: 'revenue', measureIndex: 0, operator: 'greater_than', value: '1000' },
                    { id: 'purchases', measureIndex: 1, operator: 'greater_than_or_equal', value: '5' },
                    { id: 'calculation', measureIndex: 2, operator: 'between', value: '20', valueTo: '100' },
                ],
                resultFilterGroup: {
                    operator: 'AND',
                    filters: ['revenue'],
                    groups: [{ operator: 'OR', filters: ['purchases', 'calculation'], groups: [] }],
                },
            }
            const parsed = parseBIEditorState(BIEditorView.BI, worksheet)!.config
            expect(parsed.resultFilters).toEqual(worksheet.resultFilters)
            expect(parsed.resultFilterGroup).toEqual(worksheet.resultFilterGroup)
            const query = buildBIQuery(parsed)!.query
            expect(query).toContain('sum_properties_amount > 1000')
            expect(query).toContain('count_event_2 >= 5')
            expect(query).toContain('"Revenue per purchase_3" >= 20 AND "Revenue per purchase_3" <= 100')
            expect(query).toMatch(/bi_filtered AS \(SELECT \* FROM bi_calculated WHERE .* AND .* OR /)
            expect(query).toContain('OVER (PARTITION BY bi_column_event')
            expect(query.match(/LIMIT/g)).toHaveLength(1)
            expect(query.indexOf('bi_filtered AS')).toBeGreaterThan(query.indexOf('bi_calculated AS'))
            expect(query.endsWith('LIMIT 1000')).toBe(true)
            if (compare) {
                expect(query).toContain('FROM bi_previous')
                expect(query).toContain('UNION ALL')
            }
        }
    )

    it.each(['1 OR 1=1', 'Infinity', '1; DROP TABLE events', '1e999'])(
        'rejects invalid result values instead of interpolating them: %s',
        (value) => {
            const worksheet: BIConfig = {
                ...config,
                resultFilters: [{ id: 'measure', measureIndex: 0, operator: 'greater_than', value }],
            }
            expect(buildBIQuery(worksheet)).toBeNull()
            expect(
                buildBIQuery({ ...worksheet, resultFilters: [{ ...worksheet.resultFilters![0], enabled: false }] })
            ).not.toBeNull()
        }
    )

    it('keeps totals independent of result filters and filters before reserving the summary row budget', () => {
        const query = buildBIQuery({
            ...config,
            chartType: ChartDisplayType.ActionsTable,
            totals: { rows: true },
            resultFilters: [{ id: 'measure', measureIndex: 0, operator: 'greater_than', value: '100' }],
        })!.query
        expect(query).toContain('FROM bi_calculated WHERE bi_grouping != 0 OR ((sum_properties_amount > 100))')
        expect(query).toContain('AS bi_rank FROM bi_filtered)')
    })

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
        expect(result.query).toContain('grouping(toStartOfDay(timestamp), if((event IN (SELECT bi_key FROM bi_top)')
        expect(buildBIQuery({ ...worksheet, topN: undefined, totals: undefined })!.query).toContain(
            "startsWith(toString(bi_column_event), 'Total')"
        )
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

    it('limits complete comparison groups and probes one extra group without changing the saved query', () => {
        const worksheet: BIConfig = {
            ...config,
            limit: 100,
            dateRange: { date_from: '-7d' },
            compareFilter: { compare: true },
        }
        const saved = buildBIQuery(worksheet)!
        const probe = buildBIQuery(worksheet, true)!
        expect(saved.query).toContain('bi_comparison_rank <= 50')
        expect(saved.query).toMatch(/LIMIT 100$/)
        expect(probe.query).toContain('UNION ALL')
        expect(probe.query.match(/LIMIT /g)).toHaveLength(1)
        expect(probe.query).toContain('bi_comparison_rank <= 51')
        expect(probe.query).toMatch(/LIMIT 102$/)
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
