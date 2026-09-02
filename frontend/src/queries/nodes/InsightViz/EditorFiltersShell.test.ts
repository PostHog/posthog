import { InsightVizNode, NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { checkLatestVersionsOnQuery } from '~/queries/utils'

import { buildInsightNodeFromQueryTool, withCurrentQueryMetadata } from './EditorFiltersShell'

describe('EditorFiltersShell', () => {
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

    describe('withCurrentQueryMetadata', () => {
        const suggested: InsightVizNode = {
            kind: NodeKind.InsightVizNode,
            source: {
                kind: NodeKind.TrendsQuery,
                series: [{ kind: NodeKind.EventsNode, event: '$pageleave' }],
            },
        }

        it('carries the current query log tags over and stamps the latest schema versions', () => {
            const currentSource: TrendsQuery = {
                kind: NodeKind.TrendsQuery,
                series: [{ kind: NodeKind.EventsNode, event: '$pageview' }],
                tags: { productKey: 'product_analytics' },
            }

            const node = withCurrentQueryMetadata(suggested, currentSource)

            expect(node.source.tags).toEqual({ productKey: 'product_analytics' })
            expect(checkLatestVersionsOnQuery(node)).toBe(true)
        })

        it('adds no tags key when the current query has none', () => {
            const node = withCurrentQueryMetadata(suggested, {
                kind: NodeKind.TrendsQuery,
                series: [],
            })

            expect('tags' in node.source).toBe(false)
        })
    })
})
