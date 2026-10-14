import { HogQLQueryModifiers, QuerySchema } from '~/queries/schema/schema-general'

import { WebAnalyticsTile } from './common'

export function withQueryModifiers<T extends QuerySchema>(query: T, modifiers: HogQLQueryModifiers): T {
    // Wrapper nodes (DataTableNode, InsightVizNode, DataVisualizationNode) run their source, so the modifiers go there.
    if ('source' in query && query.source) {
        return { ...query, source: withQueryModifiers(query.source as QuerySchema, modifiers) }
    }
    const existing = 'modifiers' in query ? query.modifiers : undefined
    return { ...query, modifiers: { ...existing, ...modifiers } }
}

export function applyWebQueryModifiers(tiles: WebAnalyticsTile[], modifiers: HogQLQueryModifiers): WebAnalyticsTile[] {
    // Keep the same tile objects when there is nothing to apply, so no tile refetches.
    if (Object.keys(modifiers).length === 0) {
        return tiles
    }
    return tiles.map((tile): WebAnalyticsTile => {
        switch (tile.kind) {
            case 'query':
                return { ...tile, query: withQueryModifiers(tile.query, modifiers) }
            case 'tabs':
                return {
                    ...tile,
                    tabs: tile.tabs.map((tab) => ({ ...tab, query: withQueryModifiers(tab.query, modifiers) })),
                }
            case 'section':
                return { ...tile, tiles: applyWebQueryModifiers(tile.tiles, modifiers) }
            default:
                return tile
        }
    })
}
