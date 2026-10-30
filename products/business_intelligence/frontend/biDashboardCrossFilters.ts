import { BIConfig, BIVisualizationNode } from '~/queries/schema/schema-business-intelligence'
import { isBIVisualizationNode } from '~/queries/utils'
import { DashboardTile } from '~/types'

import { BIDrillSelection, getBIDrillSelection } from './biDrilldown'
import { buildBIQuery, fieldExpression, getBIDataSourceKey, getBIResultDimensions } from './biEditorTypes'
import { isBIConditionGroup, normalizeBIConditionGroup } from './biFilterGroups'

export interface BIDashboardSelection {
    tileId: number
    title: string
    source: NonNullable<BIConfig['source']>
    selection: BIDrillSelection
}

export function getBIDashboardItemId(dashboardId: number, tileId: number, filtered: boolean): `new-${string}` {
    return `new-SQL-cross-filter-${dashboardId}-${tileId}-${filtered ? 'selection' : 'saved'}`
}

export function isCrossFilterWorksheet(query: unknown): query is BIVisualizationNode {
    return (
        !!query &&
        typeof query === 'object' &&
        isBIVisualizationNode(query as Record<string, unknown>) &&
        !!(query as BIVisualizationNode).config.source &&
        !(query as BIVisualizationNode).config.querySnapshot
    )
}

export function getBIDashboardSelectionScope(query: unknown): unknown {
    return isCrossFilterWorksheet(query)
        ? {
              source: query.config.source,
              dimensions: getBIResultDimensions(query.config),
              comparisonPeriod: query.config.comparisonPeriod,
              topN: query.config.topN,
          }
        : null
}

export function createBIDashboardSelection(
    tileId: number,
    title: string,
    query: BIVisualizationNode,
    record: Record<string, unknown>
): BIDashboardSelection | null {
    if (!isCrossFilterWorksheet(query)) {
        return null
    }
    const selection = getBIDrillSelection(query.config, record)
    if (
        !selection.filters.length ||
        selection.previous ||
        query.config.comparisonPeriod === 'previous' ||
        selection.filters.some(
            (filter) =>
                filter.operator === 'custom' &&
                filter.field.id === query.config.topN?.fieldId &&
                query.config.topN.includeOther
        )
    ) {
        return null
    }
    return { tileId, title, source: query.config.source!, selection }
}

export function applyBIDashboardSelection(
    query: BIVisualizationNode,
    active: BIDashboardSelection
): BIVisualizationNode | null {
    if (
        !isCrossFilterWorksheet(query) ||
        getBIDataSourceKey(query.config.source!) !== getBIDataSourceKey(active.source)
    ) {
        return null
    }
    const saved = query.config
    const ids = new Set(saved.filters.map(({ field }) => field.id))
    const filters = active.selection.filters.map((filter) => {
        let id = `dashboard:${filter.field.id}`
        while (ids.has(id)) {
            id += ':'
        }
        ids.add(id)
        return {
            ...filter,
            field: {
                id,
                name: filter.field.name,
                expression: fieldExpression(filter.field),
                type: filter.field.type,
                source: filter.field.source,
            },
        }
    })
    const existing = normalizeBIConditionGroup(
        saved.rowFilterGroup ?? { operator: 'AND', filters: [], groups: [] },
        saved.filters.map(({ field }) => field.id)
    )
    const config: BIConfig = {
        ...saved,
        filters: [...saved.filters, ...filters],
        rowFilterGroup: {
            operator: 'AND',
            filters: [
                ...filters.map(({ field }) => field.id),
                ...(existing.operator === 'AND' ? existing.filters : []),
            ],
            groups: existing.operator === 'AND' ? existing.groups : [existing],
        },
    }
    if (!isBIConditionGroup(config.rowFilterGroup)) {
        return null
    }
    const generated = buildBIQuery(config)
    return generated ? { ...query, config, source: { ...query.source, query: generated.query } } : null
}

export function getBIDashboardTargets(
    tiles: DashboardTile[],
    active: BIDashboardSelection | null
): Record<number, BIVisualizationNode> {
    if (!active) {
        return {}
    }
    return Object.fromEntries(
        tiles.flatMap((tile) => {
            const query = tile.insight?.query
            if (tile.id === active.tileId || !isCrossFilterWorksheet(query)) {
                return []
            }
            const filtered = applyBIDashboardSelection(query, active)
            return filtered ? [[tile.id, filtered]] : []
        })
    )
}

export function canSelectBIWorksheet(query: BIVisualizationNode): boolean {
    return (
        isCrossFilterWorksheet(query) &&
        query.config.comparisonPeriod !== 'previous' &&
        getBIResultDimensions(query.config).length > 0
    )
}
