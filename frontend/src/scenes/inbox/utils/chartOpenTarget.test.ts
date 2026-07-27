import { Node, NodeKind } from '~/queries/schema/schema-general'
import { InsightShortId } from '~/types'

import { chartOpenTarget } from './chartOpenTarget'

describe('chartOpenTarget', () => {
    const trendsChart = {
        kind: NodeKind.InsightVizNode,
        source: { kind: NodeKind.TrendsQuery, series: [] },
    } as unknown as Node

    const sqlChart = {
        kind: NodeKind.DataVisualizationNode,
        source: { kind: NodeKind.HogQLQuery, query: 'select 1' },
    } as unknown as Node

    const savedInsightChart = {
        kind: NodeKind.SavedInsightNode,
        shortId: 'abc123' as InsightShortId,
    } as unknown as Node

    it('opens the insight a saved-insight chart points at, rather than seeding a new one', () => {
        // Routed through `insightNew`, a SavedInsightNode becomes `/insights/new?q={"shortId":…}`,
        // which opens an empty editor because the node carries no query of its own.
        expect(chartOpenTarget(savedInsightChart)).toEqual({ url: '/insights/abc123', label: 'Open insight' })
    })

    it.each([
        ['no shortId at all', { kind: NodeKind.SavedInsightNode }],
        ['an empty shortId', { kind: NodeKind.SavedInsightNode, shortId: '' }],
    ])('offers nowhere to go for a saved-insight chart with %s', (_name, query: unknown) => {
        // The query is stored unparsed, so this shape reaches the renderer. Dropping the guard sends
        // the reader to `/insights/undefined` from the one chart that already can't load.
        expect(chartOpenTarget(query as Node)).toBeNull()
    })

    it.each([
        ['a trends chart', trendsChart, 'Open as new insight'],
        ['a SQL chart', sqlChart, 'Open in SQL editor'],
    ])('labels %s by where it actually lands', (_name, query: Node, label: string) => {
        expect(chartOpenTarget(query)?.label).toBe(label)
    })

    it('sends a SQL chart to the SQL editor, where its query is editable', () => {
        expect(chartOpenTarget(sqlChart)?.url).toContain('/sql')
    })

    it('offers nowhere to go for a query too large to survive the request line', () => {
        // The whole node rides in the query string and the control opens a new tab, so a chart near
        // the 20,000-character bound the backend allows would hand the reader a 414.
        const hugeChart = {
            kind: NodeKind.DataVisualizationNode,
            source: { kind: NodeKind.HogQLQuery, query: `select ${'a'.repeat(20000)}` },
        } as unknown as Node

        expect(chartOpenTarget(hugeChart)).toBeNull()
    })
})
