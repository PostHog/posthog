import { BIConfig, BIField, BIVisualizationNode } from '~/queries/schema/schema-business-intelligence'
import { NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { getBIChartRecord, getBIDrillQueries, getBIDrillSelection, getBIEffectiveQuery } from './biDrilldown'
import { buildBIQuery, DEFAULT_BI_CONFIG } from './biEditorTypes'

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
    chartType: ChartDisplayType.ActionsBar,
    rows: [{ ...field('timestamp', 'datetime'), dateBucket: 'day' }],
    columns: [field('event')],
    values: [{ field: field('properties.amount', 'float'), aggregation: 'sum' }],
    dateRange: { date_from: '-7d' },
    filters: [{ field: field('properties.environment'), operator: 'equals', value: 'production' }],
}

function buildWorksheet(config: BIConfig): { node: BIVisualizationNode } {
    return { node: { ...buildBIQuery(config)!.node, kind: NodeKind.BIVisualizationNode, config } }
}

describe('BI drill-down', () => {
    it('uses raw date and category values, escapes labels, and preserves effective dashboard filters', () => {
        const node = buildWorksheet(config)!.node
        node.source.variables = { variable: { variableId: 'variable', code_name: 'plan', value: 'starter' } }
        const effective = getBIEffectiveQuery(
            node,
            { date_from: '-30d', filterTestAccounts: true },
            { variable: { variableId: 'variable', code_name: 'plan', value: 'pro' } }
        )
        const record = getBIChartRecord(node, 'bi_row_timestamp', '2026-06-01', "purchase's")
        const selection = getBIDrillSelection(config, record)
        const queries = getBIDrillQueries(effective, selection)!
        expect(queries.rows.source.query).toContain("toStartOfDay(timestamp) = '2026-06-01'")
        expect(queries.rows.source.query).toContain("event = 'purchase\\'s'")
        expect(queries.rows.source.query).toContain("properties.environment = 'production'")
        expect(queries.rows.source.query).toContain('SELECT * FROM events')
        expect(queries.rows.source.filters).toEqual({
            dateRange: { date_from: '-30d', date_to: undefined, explicitDate: false },
            filterTestAccounts: true,
        })
        expect(queries.rows.source.variables?.variable.value).toBe('pro')
        expect(queries.worksheet?.source.variables?.variable.value).toBe('pro')
        expect(node.source.variables?.variable.value).toBe('starter')
        expect(queries.rows.source).not.toHaveProperty('biConfig')
        expect(queries.worksheet?.config?.dateRange).toEqual({
            date_from: '-30d',
            date_to: undefined,
            explicitDate: false,
        })
        expect(queries.worksheet?.config?.filters).toHaveLength(3)
        expect(selection.filters.map(({ operator, value }) => ({ operator, value }))).toEqual([
            { operator: 'equals', value: '2026-06-01' },
            { operator: 'equals', value: "purchase's" },
        ])
    })

    it.each([false, true])('converts numeric date dimensions to SQL dates (comparison: %s)', (previous) => {
        const worksheet: BIConfig = {
            ...config,
            rows: [field('created_at', 'date')],
            compareFilter: { compare: previous },
        }
        const selection = getBIDrillSelection(worksheet, {
            bi_row_created_at: 1780272000,
            bi_comparison: previous ? 'Previous period' : 'Current period',
        })
        const queries = getBIDrillQueries(buildWorksheet(worksheet).node, selection)!
        expect(queries.rows.source.query).toContain(
            previous ? "{filters.compareDate(created_at)} = '2026-06-01'" : "created_at = '2026-06-01'"
        )
        expect(queries.rows.source.query).not.toContain("'1780272000'")
    })

    it('uses comparison dates for previous-period points without treating their label as a category', () => {
        const node = buildWorksheet({ ...config, compareFilter: { compare: true } })!.node
        const record = getBIChartRecord(node, 'bi_row_timestamp', '2026-06-01', 'Previous period · purchase · web')
        const selection = getBIDrillSelection(node.config, record)
        const queries = getBIDrillQueries(node, selection)!
        expect(selection.previous).toBe(true)
        expect(queries.rows.source.query).toContain('{filters.previous}')
        expect(queries.rows.source.query).toContain("toStartOfDay({filters.compareDate(timestamp)}) = '2026-06-01'")
        expect(queries.rows.source.query).toContain("event = 'purchase · web'")
        expect(queries.worksheet).toBeNull()
    })

    it('selects the remainder with null-safe membership and removes the top N restriction', () => {
        const worksheet = { ...config, topN: { fieldId: 'event', count: 3, measureIndex: 0, includeOther: true } }
        const selection = getBIDrillSelection(worksheet, { bi_column_event: 'Other' })
        const queries = getBIDrillQueries(buildWorksheet(worksheet)!.node, selection)!
        const sql = queries.rows.source.query
        expect(sql).toContain('((event IS NOT NULL AND event IN')
        expect(sql).toContain('= false')
        expect(sql).toContain('WHERE bi_key IS NOT NULL')
        expect(sql).toContain('GROUP BY bi_key ORDER BY sum(properties.amount) DESC, bi_key ASC LIMIT 3')
        expect(sql).not.toContain("event = 'Other'")
        expect(queries.worksheet?.config?.topN).toBeUndefined()
    })

    it.each([
        ['Other (category)', "event = 'Other'"],
        [null, 'event IS NULL'],
    ])('distinguishes real Other and null from the remainder (%s)', (label, condition) => {
        const worksheet = { ...config, topN: { fieldId: 'event', count: 3, measureIndex: 0, includeOther: true } }
        const selection = getBIDrillSelection(worksheet, { bi_column_event: label })
        const queries = getBIDrillQueries(buildWorksheet(worksheet)!.node, selection)!
        expect(queries.rows.source.query).toContain(condition)
        expect(queries.worksheet?.config?.topN).toBeUndefined()
    })

    it('expands pivot hierarchy keys and leaves subtotal dimensions unfiltered', () => {
        const worksheet: BIConfig = {
            ...config,
            chartType: ChartDisplayType.TwoDimensionalHeatmap,
            rows: [field('event'), field('properties.browser')],
            columns: [field('properties.country')],
            totals: { rows: true, columns: true, subtotals: true },
        }
        const selection = getBIDrillSelection(worksheet, {
            bi_rows: '["purchase","Total"]',
            bi_column_properties_country: 'US',
        })
        expect(selection.filters.map((filter) => [filter.field.name, filter.operator, filter.value])).toEqual([
            ['event', 'equals', 'purchase'],
            ['properties.country', 'equals', 'US'],
        ])
        expect(getBIDrillSelection(worksheet, { bi_rows: '["Total (category)","Total"]' }).filters[0]).toMatchObject({
            operator: 'equals',
            value: 'Total',
        })
    })

    it('filters empty strings rather than silently dropping the selected category', () => {
        const selection = getBIDrillSelection(config, { bi_column_event: '' })
        expect(selection.filters[0]).toMatchObject({ operator: 'in', values: [''] })
        expect(getBIDrillQueries(buildWorksheet(config)!.node, selection)!.rows.source.query).toContain("event IN ('')")
    })

    it.each([
        ['(empty)', 'event IS NULL'],
        ['(empty) (category)', "event = '(empty)'"],
    ])('preserves the previous period for a null or literal empty label (%s)', (label, condition) => {
        const worksheet = { ...config, compareFilter: { compare: true } }
        const node = buildWorksheet(worksheet)!.node
        expect(node.source.query).toContain("if(event IS NULL, '(empty)'")
        const record = getBIChartRecord(node, 'bi_row_timestamp', '2026-06-01', `Previous period · ${label}`)
        const selection = getBIDrillSelection(worksheet, record)
        expect(selection.previous).toBe(true)
        expect(getBIDrillQueries(node, selection)!.rows.source.query).toContain(condition)
    })
})
