import equal from 'fast-deep-equal'
import { getEventNamesForAction } from 'lib/utils'

import { examples } from '~/queries/examples'
import {
    DataTableNode,
    DataVisualizationNode,
    HogQuery,
    InsightNodeKind,
    InsightQueryNode,
    InsightVizNode,
    Node,
    NodeKind,
} from '~/queries/schema/schema-general'
import { isInsightQueryWithSeries, setLatestVersionsOnQuery } from '~/queries/utils'
import {
    ActionType,
    DashboardTile,
    DashboardType,
    FilterType,
    InsightModel,
    InsightType,
    QueryBasedInsightModel,
} from '~/types'

import { nodeKindToDefaultQuery } from '../InsightQuery/defaults'
import { filtersToQueryNode } from '../InsightQuery/utils/filtersToQueryNode'
import { ApiError } from 'lib/api'

const TOP_LEVEL_LABELS: Record<string, string> = {
    kind: 'Insight Type',
    source: 'Query Settings',
}
const SOURCE_FIELD_LABELS: Record<string, string> = {
    breakdownFilter: 'Breakdowns',
    compareFilter: 'Compare Filter',
    dateRange: 'Date Range',
    filterTestAccounts: 'Test Account Filtering',
    interval: 'Interval',
    kind: 'Query Kind',
    properties: 'Global Property Filters',
    samplingFactor: 'Sampling',
    series: 'Series',
    trendsFilter: 'Display Options',
}

const isObject = (value: any): value is Record<string, any> => {
    return value !== null && typeof value === 'object'
}

const deepEqual = (a: any, b: any): boolean => {
    if (a === b) {
        return true
    }

    if (Array.isArray(a) && Array.isArray(b)) {
        if (a.length !== b.length) {
            return false
        }
        const bUsed = new Array(b.length).fill(false)
        return a.every((itemA) => b.some((itemB, i) => !bUsed[i] && deepEqual(itemA, itemB) && (bUsed[i] = true)))
    }

    if (isObject(a) && isObject(b)) {
        const keysA = Object.keys(a)
        const keysB = Object.keys(b)
        if (keysA.length !== keysB.length) {
            return false
        }
        return keysA.every((key) => deepEqual(a[key], b[key]))
    }

    return false
}

export const compareTopLevelSections = (obj1: any, obj2: any): string[] => {
    const changedLabels: string[] = []

    // Top-level keys (e.g. kind, source)
    const keys = new Set([...Object.keys(obj1 || {}), ...Object.keys(obj2 || {})])

    for (const key of keys) {
        const val1 = obj1?.[key]
        const val2 = obj2?.[key]

        if (!deepEqual(val1, val2)) {
            if (key === 'source' && isObject(val1) && isObject(val2)) {
                // Compare one level deeper in 'source'
                const innerKeys = new Set([...Object.keys(val1), ...Object.keys(val2)])
                for (const innerKey of innerKeys) {
                    const subVal1 = val1[innerKey]
                    const subVal2 = val2[innerKey]
                    if (!deepEqual(subVal1, subVal2)) {
                        const label = SOURCE_FIELD_LABELS[innerKey] || `source.${innerKey}`
                        changedLabels.push(label)
                    }
                }
            } else {
                const label = TOP_LEVEL_LABELS[key] || key
                changedLabels.push(label)
            }
        }
    }

    return changedLabels
}

export const getAllEventNames = (query: InsightQueryNode, allActions: ActionType[]): string[] => {
    if (!isInsightQueryWithSeries(query)) {
        return []
    }

    const allEvents = query.series.flatMap((e) => {
        if (e.kind == NodeKind.EventsNode) {
            return e.event
        } else if (e.kind == NodeKind.ActionsNode) {
            return getEventNamesForAction(e.id, allActions)
        }
    })

    // has one "all events" event
    if (allEvents.some((e) => e === null)) {
        return []
    }

    // remove duplicates and empty events
    return Array.from(new Set(allEvents.filter((e): e is string => !!e)))
}

export const getCachedResults = (
    cachedInsight: Partial<QueryBasedInsightModel> | undefined | null,
    query: InsightQueryNode
): Partial<QueryBasedInsightModel> | undefined => {
    if (!cachedInsight) {
        return undefined
    }

    let cachedQueryNode: Node | undefined

    if (cachedInsight.query) {
        cachedQueryNode = cachedInsight.query
        if ('source' in cachedInsight.query) {
            cachedQueryNode = cachedInsight.query.source as Node
        }
    } else {
        return undefined
    }

    // only set the cached result when the filters match the currently set ones
    if (!equal(cachedQueryNode, query)) {
        return undefined
    }

    return cachedInsight
}

// these types exist so that the return type reflects the input model
// i.e. when given a partial model the return model is types as
// partial as well
type InputInsightModel = InsightModel | Partial<InsightModel>

type ReturnInsightModel<T> = T extends InsightModel
    ? QueryBasedInsightModel
    : T extends Partial<InsightModel>
    ? Partial<QueryBasedInsightModel>
    : never

/** Get an insight with `query` only. Eventual `filters` will be converted.  */
export function getQueryBasedInsightModel<T extends InputInsightModel>(insight: T): ReturnInsightModel<T> {
    const { filters, ...baseInsight } = insight
    return { ...baseInsight, query: getQueryFromInsightLike(insight) } as unknown as ReturnInsightModel<T>
}

/** Get a `query` from an object that potentially has `filters` instead of a `query`.  */
export function getQueryFromInsightLike(insight: {
    query?: Node<Record<string, any>> | null
    filters?: Partial<FilterType>
}): Node<Record<string, any>> | null {
    let query
    if (insight.query) {
        query = insight.query
    } else if (insight.filters && Object.keys(insight.filters).filter((k) => k != 'filter_test_accounts').length > 0) {
        query = { kind: NodeKind.InsightVizNode, source: filtersToQueryNode(insight.filters) } as InsightVizNode
    } else {
        query = null
    }

    return query
}

export const queryFromFilters = (filters: Partial<FilterType>): InsightVizNode => ({
    kind: NodeKind.InsightVizNode,
    source: filtersToQueryNode(filters),
})

export const queryFromKind = (kind: InsightNodeKind, filterTestAccountsDefault: boolean): InsightVizNode =>
    setLatestVersionsOnQuery({
        kind: NodeKind.InsightVizNode,
        source: { ...nodeKindToDefaultQuery[kind], ...(filterTestAccountsDefault ? { filterTestAccounts: true } : {}) },
    })

export const getDefaultQuery = (
    insightType: InsightType,
    filterTestAccountsDefault: boolean
): DataTableNode | DataVisualizationNode | HogQuery | InsightVizNode => {
    if ([InsightType.SQL, InsightType.JSON, InsightType.HOG].includes(insightType)) {
        if (insightType === InsightType.JSON) {
            return examples.TotalEventsTable as DataTableNode
        } else if (insightType === InsightType.SQL) {
            return examples.DataVisualization as DataVisualizationNode
        } else if (insightType === InsightType.HOG) {
            return examples.Hoggonacci as HogQuery
        }
    } else {
        if (insightType === InsightType.TRENDS) {
            return queryFromKind(NodeKind.TrendsQuery, filterTestAccountsDefault)
        } else if (insightType === InsightType.FUNNELS) {
            return queryFromKind(NodeKind.FunnelsQuery, filterTestAccountsDefault)
        } else if (insightType === InsightType.RETENTION) {
            return queryFromKind(NodeKind.RetentionQuery, filterTestAccountsDefault)
        } else if (insightType === InsightType.PATHS) {
            return queryFromKind(NodeKind.PathsQuery, filterTestAccountsDefault)
        } else if (insightType === InsightType.STICKINESS) {
            return queryFromKind(NodeKind.StickinessQuery, filterTestAccountsDefault)
        } else if (insightType === InsightType.LIFECYCLE) {
            return queryFromKind(NodeKind.LifecycleQuery, filterTestAccountsDefault)
        } else if (insightType === InsightType.CALENDAR_HEATMAP) {
            return queryFromKind(NodeKind.CalendarHeatmapQuery, filterTestAccountsDefault)
        }
    }

    throw new Error('encountered unexpected type for view')
}

/** Get a dashboard where eventual `filters` based tiles are converted to `query` based ones. */
export const getQueryBasedDashboard = (
    dashboard: DashboardType<InsightModel> | null
): DashboardType<QueryBasedInsightModel> | null => {
    if (dashboard == null) {
        return null
    }

    return {
        ...dashboard,
        tiles: dashboard.tiles?.map(
            (tile) =>
                ({
                    ...tile,
                    ...(tile.insight != null ? { insight: getQueryBasedInsightModel(tile.insight) } : {}),
                } as DashboardTile<QueryBasedInsightModel>)
        ),
    }
}

export const extractValidationError = (error: Error | Record<string, any> | null | undefined): string | null => {
    if (error instanceof ApiError || (error && typeof error === 'object' && 'status' in error)) {
        // We use 512 for query timeouts
        // Async queries put the error message on data.error_message, while synchronous ones use detail
        return error?.status === 400 || error?.status === 512
            ? (error.detail || error.data?.error_message)?.replace('Try ', 'Try\u00A0') // Add unbreakable space for better line breaking
            : null
    }

    return null
}
