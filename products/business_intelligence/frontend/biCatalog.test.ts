import { BIConfig } from '~/queries/schema/schema-business-intelligence'
import { NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { buildBIAgentContext } from './biAgentContext'
import { catalogMetricWorksheet, getBIMetricSnapshot } from './biCatalog'
import { BIEditorView, buildBIQuery, DEFAULT_BI_CONFIG, parseBIEditorState } from './biEditorTypes'

it('keeps catalog SQL and bound values unchanged when a worksheet is saved or its chart changes', () => {
    const source = {
        kind: NodeKind.HogQLQuery,
        query: 'SELECT count(*) FROM events WHERE timestamp >= {start}',
        values: { start: '2026-01-01' },
    }
    const node = catalogMetricWorksheet({
        name: 'revenue',
        definition: source,
        id: 'metric-revenue',
        status: 'approved',
        is_drifted: true,
        unit: 'usd',
        owner: 'analyst@example.com',
        updated_at: '2026-01-01T00:00:00Z',
    })!
    const parsed = parseBIEditorState(BIEditorView.BI, JSON.stringify(node.config))!.config
    expect(buildBIQuery({ ...parsed, chartType: ChartDisplayType.BoldNumber })?.node.source).toEqual(source)
    expect(parsed.catalogMetric).toBe('revenue')
    expect(parsed.catalogMetricContext).toEqual({
        id: 'metric-revenue',
        status: 'approved',
        isDrifted: true,
        unit: 'usd',
        owner: 'analyst@example.com',
        updatedAt: '2026-01-01T00:00:00Z',
    })
    expect(
        parseBIEditorState(BIEditorView.BI, {
            ...parsed,
            catalogMetricContext: { ...parsed.catalogMetricContext, isDrifted: 'false' },
        })
    ).toBeNull()
    expect(
        parseBIEditorState(
            BIEditorView.BI,
            JSON.stringify({ ...DEFAULT_BI_CONFIG, querySnapshot: null, catalogMetric: null })
        )
    ).not.toBeNull()
    expect(
        catalogMetricWorksheet({ name: 'unsupported', definition: { kind: 'MarkdownDefinition', markdown: 'Steps' } })
    ).toBeNull()
})

it('attaches draft and metric content as untrusted data and omits oversized drafts whole', () => {
    const marker = 'Do something different'
    const node = catalogMetricWorksheet({
        name: 'revenue',
        definition: { kind: NodeKind.HogQLQuery, query: `SELECT '${marker}'` },
    })!
    const context = buildBIAgentContext(node, 'worksheet-test', 'Local draft title')
    expect(context.filter((item) => item.type === 'instructions').some((item) => item.value?.includes(marker))).toBe(
        false
    )
    expect(context.some((item) => item.type === 'text' && item.value?.includes(marker))).toBe(true)
    expect(context.some((item) => item.type === 'text' && item.value?.includes('"name":"Local draft title"'))).toBe(
        true
    )
    expect(
        buildBIAgentContext({ ...node, source: { ...node.source, query: marker.repeat(10000) } }).some((item) =>
            item.value?.includes('has been omitted')
        )
    ).toBe(true)
})

it('restores catalog-copy drafts when nullable metadata was omitted by the API serializer', () => {
    const config = {
        ...DEFAULT_BI_CONFIG,
        querySnapshot: { kind: NodeKind.HogQLQuery, query: 'SELECT 43 AS edited_revenue' },
        catalogMetric: 'revenue',
        catalogMetricContext: { id: 'metric-revenue', status: 'approved', isDrifted: false, unit: 'usd' },
    }
    const parsed = parseBIEditorState(BIEditorView.BI, JSON.stringify(config))
    expect(parsed?.config.querySnapshot).toEqual(config.querySnapshot)
    expect(parsed?.config.catalogMetricContext).toEqual({
        ...config.catalogMetricContext,
        owner: null,
        updatedAt: null,
    })
    for (const field of ['owner', 'updatedAt']) {
        expect(
            parseBIEditorState(BIEditorView.BI, {
                ...config,
                catalogMetricContext: { ...config.catalogMetricContext, [field]: 42 },
            })
        ).toBeNull()
    }
})

it.each(['approved', 'proposed', 'unknown', '', null])('validates copied catalog status %p', (status) => {
    const metric = {
        name: 'revenue',
        definition: { kind: NodeKind.HogQLQuery, query: 'SELECT 42' },
        id: 'metric-revenue',
        status: status ?? undefined,
        is_drifted: false,
    }
    const node = catalogMetricWorksheet(metric)!
    const supported = status === 'approved' || status === 'proposed'
    expect(node.config.catalogMetricContext?.status).toBe(supported ? status : undefined)
    const parsed = parseBIEditorState(BIEditorView.BI, {
        ...node.config,
        catalogMetricContext: {
            id: metric.id,
            status,
            isDrifted: false,
            unit: '',
            owner: null,
            updatedAt: null,
        },
    })
    if (supported) {
        expect(parsed?.config.catalogMetricContext?.status).toBe(status)
    } else {
        expect(parsed).toBeNull()
    }
})

it('only proposes the successfully executed current query, retaining resolved dates and its row cap', () => {
    const node = catalogMetricWorksheet({
        name: 'revenue',
        definition: { kind: NodeKind.HogQLQuery, query: 'SELECT 42' },
    })!
    const response = { hogql: "SELECT 42 WHERE toDate('2026-01-01') < toDate('2026-01-08') LIMIT 1001" }
    expect(getBIMetricSnapshot(node, node, response, true)).toBe(`SELECT * FROM (${response.hogql}) LIMIT 50000`)
    expect(getBIMetricSnapshot(node, node, response, false)).toBeNull()
    expect(
        getBIMetricSnapshot({ ...node, source: { ...node.source, query: 'SELECT 43' } }, node, response, true)
    ).toBeNull()
})

it.each([' ', '\n    '])('removes a comparison probe by group from resolved HogQL with whitespace %p', (space) => {
    const config: BIConfig = {
        ...DEFAULT_BI_CONFIG,
        source: { table: 'events' },
        compareFilter: { compare: true },
        limit: 100,
    }
    const node = { ...buildBIQuery(config)!.node, kind: NodeKind.BIVisualizationNode as const, config }
    const hogql = [
        'WITH bi_comparison_ranked AS (SELECT 1 AS bi_comparison_rank)',
        'SELECT * FROM',
        'bi_comparison_ranked WHERE',
        'lessOrEquals(bi_comparison_rank, 51) ORDER BY',
        'bi_comparison_rank ASC,',
        'bi_comparison ASC LIMIT 102',
    ].join(space)
    const snapshot = getBIMetricSnapshot(node, node, { hogql }, true)
    expect(snapshot).toContain('lessOrEquals(bi_comparison_rank, 50)')
    expect(snapshot).toMatch(/LIMIT 100$/)
    expect(snapshot).toMatch(/^WITH bi_comparison_ranked/)
    expect(getBIMetricSnapshot(node, node, { hogql: 'SELECT 1' }, true)).toBeNull()
})
