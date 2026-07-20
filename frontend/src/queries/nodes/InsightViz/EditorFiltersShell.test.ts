import { NodeKind } from '~/queries/schema/schema-general'

import { buildInsightNodeFromQueryTool } from './EditorFiltersShell'

describe('buildInsightNodeFromQueryTool', () => {
    it.each([
        ['query-trends', NodeKind.TrendsQuery],
        ['query-funnel', NodeKind.FunnelsQuery],
        ['query-retention', NodeKind.RetentionQuery],
        ['query-paths', NodeKind.PathsQuery],
        ['query-stickiness', NodeKind.StickinessQuery],
        ['query-lifecycle', NodeKind.LifecycleQuery],
    ])('wraps %s input into an InsightVizNode with kind %s', (toolName, kind) => {
        const innerInput = { series: [{ event: '$pageview' }] }

        expect(buildInsightNodeFromQueryTool(toolName, innerInput)).toEqual({
            kind: NodeKind.InsightVizNode,
            source: { ...innerInput, kind },
        })
    })

    it('returns null for a tool name outside the core query-* set (e.g. an actors drill-down)', () => {
        expect(buildInsightNodeFromQueryTool('query-trends-actors', { series: [] })).toBeNull()
    })

    it('returns null when the inner input is null', () => {
        expect(buildInsightNodeFromQueryTool('query-trends', null)).toBeNull()
    })
})
