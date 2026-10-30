import { CapturedPersonsModal } from 'lib/components/ResultMenu/personsModalCapture'
import { BREAKDOWN_OTHER_STRING_LABEL } from 'scenes/insights/utils'

import { ActorsQuery, InsightQueryNode, InsightVizNode, NodeKind } from '~/queries/schema/schema-general'
import { hogql, isActorsQuery, isInsightVizNode } from '~/queries/utils'
import { DashboardTile, FilterLogicalOperator, HogQLPropertyFilter, PropertyFilterType } from '~/types'

const FILTER_LABEL = 'Dashboard result selection'
const ACTOR_KINDS = new Set([
    NodeKind.InsightActorsQuery,
    NodeKind.FunnelsActorsQuery,
    NodeKind.StickinessActorsQuery,
    NodeKind.PathsV2ActorsQuery,
])
const INSIGHT_KINDS = new Set([
    NodeKind.TrendsQuery,
    NodeKind.FunnelsQuery,
    NodeKind.RetentionQuery,
    NodeKind.LifecycleQuery,
    NodeKind.StickinessQuery,
    NodeKind.PathsQuery,
    NodeKind.PathsV2Query,
])

export interface DashboardResultSelection {
    dashboardId: number
    tileId: number
    label: string
    query: ActorsQuery
}

export function getDashboardResultItemId(dashboardId: number, tileId: number): `new-${string}` {
    return `new-AdHoc.result-filter-${dashboardId}-${tileId}`
}

function withoutResultFilter(value: unknown): unknown {
    if (Array.isArray(value)) {
        return value
            .filter((item) => !(item?.type === PropertyFilterType.HogQL && item?.label === FILTER_LABEL))
            .map(withoutResultFilter)
    }
    if (value && typeof value === 'object') {
        if (
            'type' in value &&
            value.type === FilterLogicalOperator.And &&
            'values' in value &&
            Array.isArray(value.values) &&
            value.values.length === 2
        ) {
            const addedGroup = value.values[1]
            if (
                addedGroup?.type === FilterLogicalOperator.And &&
                addedGroup.values?.length === 1 &&
                addedGroup.values[0]?.type === PropertyFilterType.HogQL &&
                addedGroup.values[0]?.label === FILTER_LABEL
            ) {
                return withoutResultFilter(value.values[0])
            }
        }
        return Object.fromEntries(
            Object.entries(value)
                .filter(([key, item]) => item !== undefined && key !== 'response' && key !== 'tags')
                .map(([key, item]) => [key, withoutResultFilter(item)])
        )
    }
    return value
}

type FilterableInsight = Exclude<InsightQueryNode, { kind: NodeKind.WebOverviewQuery | NodeKind.WebStatsTableQuery }>

export function canFilterInsight(query: unknown): query is InsightVizNode<FilterableInsight> {
    if (!query || typeof query !== 'object' || !isInsightVizNode(query) || !INSIGHT_KINDS.has(query.source.kind)) {
        return false
    }
    const source = query.source
    return (
        !(
            'series' in source &&
            source.series?.some((series) => series.kind !== NodeKind.EventsNode && series.kind !== NodeKind.ActionsNode)
        ) &&
        !('customAggregationTarget' in source && source.customAggregationTarget) &&
        !('retentionFilter' in source && source.retentionFilter?.customAggregationTarget)
    )
}

export function getDashboardResultActors(request: CapturedPersonsModal): ActorsQuery | null {
    const query =
        request.rowsQuery?.source ?? (request.query ? { kind: NodeKind.ActorsQuery, source: request.query } : null)
    if (
        !isActorsQuery(query) ||
        !query.source ||
        !ACTOR_KINDS.has(query.source.kind) ||
        !('source' in query.source) ||
        !canFilterInsight({ kind: NodeKind.InsightVizNode, source: query.source.source })
    ) {
        return null
    }
    const breakdown =
        'funnelStepBreakdown' in query.source
            ? query.source.funnelStepBreakdown
            : 'breakdown' in query.source
              ? query.source.breakdown
              : undefined
    if ([breakdown].flat().includes(BREAKDOWN_OTHER_STRING_LABEL)) {
        return null
    }
    const source = withoutResultFilter(query.source) as NonNullable<ActorsQuery['source']>
    if (
        source.kind === NodeKind.InsightActorsQuery &&
        source.source.kind === NodeKind.TrendsQuery &&
        Array.isArray(source.breakdown) &&
        source.source.breakdownFilter &&
        !source.source.breakdownFilter.breakdowns?.length &&
        source.source.breakdownFilter.breakdown_type !== 'cohort'
    ) {
        if (source.breakdown.length !== 1) {
            return null
        }
        source.breakdown = source.breakdown[0]
    }
    return { kind: NodeKind.ActorsQuery, source }
}

export function getDashboardResultTargets(
    tiles: DashboardTile[],
    selection: DashboardResultSelection | null
): Record<number, InsightVizNode> {
    if (!selection) {
        return {}
    }
    const filter: HogQLPropertyFilter = {
        type: PropertyFilterType.HogQL,
        key: hogql`matchesInsight(${JSON.stringify(selection.query)})`,
        label: FILTER_LABEL,
    }
    return Object.fromEntries(
        tiles.flatMap((tile) => {
            const query = tile.insight?.query
            if (
                tile.id === selection.tileId ||
                tile.filters_overrides?.ignoreDashboardFilters ||
                !canFilterInsight(query)
            ) {
                return []
            }
            const properties = query.source.properties
            return [
                [
                    tile.id,
                    {
                        ...query,
                        source: {
                            ...query.source,
                            properties:
                                !properties || Array.isArray(properties)
                                    ? [...(properties ?? []), filter]
                                    : {
                                          type: FilterLogicalOperator.And,
                                          values: [properties, { type: FilterLogicalOperator.And, values: [filter] }],
                                      },
                        },
                    },
                ],
            ]
        })
    )
}

export function getDashboardResultFilterLink(
    currentUrl: string,
    selection: DashboardResultSelection,
    remove = false
): string {
    const url = new URL(currentUrl)
    const hash = new URLSearchParams(url.hash.slice(1))
    if (remove) {
        hash.delete('insight_filter')
    } else {
        hash.delete('bi_filter')
        hash.set('insight_filter', JSON.stringify(selection))
    }
    return `${url.pathname}${url.search}#${hash}`
}

export function readDashboardResultFilter(value: unknown): DashboardResultSelection | null {
    try {
        const selection = typeof value === 'string' ? JSON.parse(value) : value
        if (
            !selection ||
            !Number.isSafeInteger(selection.dashboardId) ||
            !Number.isSafeInteger(selection.tileId) ||
            typeof selection.label !== 'string' ||
            !isActorsQuery(selection.query)
        ) {
            return null
        }
        const query = getDashboardResultActors({
            title: '',
            rowsQuery: { kind: NodeKind.DataTableNode, source: selection.query },
        })
        return query
            ? {
                  dashboardId: selection.dashboardId,
                  tileId: selection.tileId,
                  label: selection.label.slice(0, 300),
                  query,
              }
            : null
    } catch {
        return null
    }
}
