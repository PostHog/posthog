import { NodeKind, QuerySchema, WebAnalyticsQueryModifiers } from '~/queries/schema/schema-general'

import { WebAnalyticsTile } from './common'

// The query schemas reject unknown fields, so only kinds built on WebAnalyticsQueryBase may carry webQueryModifiers.
const WEB_ANALYTICS_QUERY_KINDS = new Set<NodeKind>([
    NodeKind.WebOverviewQuery,
    NodeKind.WebStatsTableQuery,
    NodeKind.WebExternalClicksTableQuery,
    NodeKind.WebBotsTableQuery,
    NodeKind.WebAgentAnalyticsQuery,
    NodeKind.WebGoalsQuery,
    NodeKind.WebVitalsQuery,
    NodeKind.WebVitalsPathBreakdownQuery,
    NodeKind.WebPageURLSearchQuery,
    NodeKind.WebNotableChangesQuery,
])

// These nodes run their source, so the modifiers go there. WebVitalsQuery also has a source, but it takes the
// modifiers itself and its source is a TrendsQuery, which rejects them.
const WRAPPER_QUERY_KINDS = new Set<NodeKind>([
    NodeKind.DataTableNode,
    NodeKind.InsightVizNode,
    NodeKind.DataVisualizationNode,
])

export function withWebQueryModifiers<T extends QuerySchema>(query: T, modifiers: WebAnalyticsQueryModifiers): T {
    if (WEB_ANALYTICS_QUERY_KINDS.has(query.kind)) {
        const existing = 'webQueryModifiers' in query ? query.webQueryModifiers : undefined
        return { ...query, webQueryModifiers: { ...existing, ...modifiers } }
    }
    if (WRAPPER_QUERY_KINDS.has(query.kind) && 'source' in query && query.source) {
        return { ...query, source: withWebQueryModifiers(query.source as QuerySchema, modifiers) }
    }
    return query
}

export function withoutWebQueryModifiers<T extends QuerySchema>(query: T): T {
    if ('webQueryModifiers' in query && query.webQueryModifiers) {
        const { webQueryModifiers: _, ...rest } = query
        return rest as T
    }
    if (WRAPPER_QUERY_KINDS.has(query.kind) && 'source' in query && query.source) {
        return { ...query, source: withoutWebQueryModifiers(query.source as QuerySchema) }
    }
    return query
}

export function applyWebQueryModifiers(
    tiles: WebAnalyticsTile[],
    modifiers: WebAnalyticsQueryModifiers
): WebAnalyticsTile[] {
    // Keep the same tile objects when there is nothing to apply, so no tile refetches.
    if (Object.keys(modifiers).length === 0) {
        return tiles
    }
    return tiles.map((tile): WebAnalyticsTile => {
        switch (tile.kind) {
            case 'query':
                return { ...tile, query: withWebQueryModifiers(tile.query, modifiers) }
            case 'tabs':
                return {
                    ...tile,
                    tabs: tile.tabs.map((tab) => ({ ...tab, query: withWebQueryModifiers(tab.query, modifiers) })),
                }
            case 'section':
                return { ...tile, tiles: applyWebQueryModifiers(tile.tiles, modifiers) }
            default:
                return tile
        }
    })
}
