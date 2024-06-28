import { JSONContent } from '@tiptap/core'
import { isEmptyObject } from 'lib/utils'

import {
    breakdownFilterToQuery,
    compareFilterToQuery,
    exlusionEntityToNode,
    funnelsFilterToQuery,
    lifecycleFilterToQuery,
    pathsFilterToQuery,
    retentionFilterToQuery,
    stickinessFilterToQuery,
    trendsFilterToQuery,
} from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import {
    isLegacyFunnelsExclusion,
    isLegacyFunnelsFilter,
    isLegacyLifecycleFilter,
    isLegacyPathsFilter,
    isLegacyRetentionFilter,
    isLegacyStickinessFilter,
    isLegacyTrendsFilter,
} from '~/queries/nodes/InsightQuery/utils/legacy'
import {
    InsightVizNode,
    NodeKind,
    STICKINESS_FILTER_PROPERTIES,
    StickinessFilter,
    StickinessFilterLegacy,
    TRENDS_FILTER_PROPERTIES,
    TrendsFilter,
    TrendsFilterLegacy,
} from '~/queries/schema'
import { FunnelExclusionLegacy, NotebookNodeType, NotebookType } from '~/types'

// NOTE: Increment this number when you add a new content migration
// It will bust the cache on the localContent in the notebookLogic
// so that the latest content will fall back to the remote content which
// is filtered through the migrate function below that ensures integrity
export const NOTEBOOKS_VERSION = '1'

export function migrate(notebook: NotebookType): NotebookType {
    let content = notebook.content?.content

    if (!content) {
        return notebook
    }

    content = convertInsightToQueryNode(content)
    content = convertInsightQueryStringsToObjects(content)
    content = convertInsightQueriesToNewSchema(content)
    return { ...notebook, content: { type: 'doc', content: content } }
}

function convertInsightToQueryNode(content: JSONContent[]): JSONContent[] {
    return content.map((node) => {
        if (node.type != 'ph-insight') {
            return node
        }

        return {
            ...node,
            type: NotebookNodeType.Query,
            attrs: {
                nodeId: node.attrs?.nodeId,
                query: { kind: NodeKind.SavedInsightNode, shortId: node.attrs?.id },
            },
        }
    })
}

function convertInsightQueryStringsToObjects(content: JSONContent[]): JSONContent[] {
    return content.map((node) => {
        if (
            !(
                node.type == NotebookNodeType.Query &&
                node.attrs &&
                'query' in node.attrs &&
                typeof node.attrs.query === 'string'
            )
        ) {
            return node
        }

        let query

        try {
            query = JSON.parse(node.attrs.query)
        } catch (e) {
            query = {
                kind: NodeKind.DataTableNode,
                source: {
                    kind: NodeKind.EventsQuery,
                    select: ['*', 'event', 'person', 'timestamp'],
                    orderBy: ['timestamp DESC'],
                    after: '-24h',
                    limit: 100,
                },
            }
        }

        return {
            ...node,
            attrs: {
                ...node.attrs,
                query,
            },
        }
    })
}

function convertInsightQueriesToNewSchema(content: JSONContent[]): JSONContent[] {
    return content.map((node) => {
        if (
            !(
                node.type == NotebookNodeType.Query &&
                node.attrs &&
                'query' in node.attrs &&
                typeof node.attrs.query === 'object' &&
                node.attrs.query['kind'] === 'InsightVizNode'
            )
        ) {
            return node
        }

        const insightQuery = node.attrs.query as InsightVizNode
        const query = insightQuery.source

        /*
         * Insight filters
         */
        if (query.kind === NodeKind.TrendsQuery && isLegacyTrendsFilter(query.trendsFilter as any)) {
            const compareFilter = compareFilterToQuery(query.trendsFilter as any)
            if (!isEmptyObject(compareFilter)) {
                query.compareFilter = compareFilter
            }

            delete (query.trendsFilter as TrendsFilterLegacy).compare
            delete (query.trendsFilter as TrendsFilterLegacy).compare_to

            query.trendsFilter = Object.fromEntries(
                Object.entries(query.trendsFilter as TrendsFilter)
                    .filter(([k, _]) => TRENDS_FILTER_PROPERTIES.has(k as keyof TrendsFilter))
                    .concat(Object.entries(trendsFilterToQuery(query.trendsFilter as any)))
            )
        }

        if (query.kind === NodeKind.FunnelsQuery) {
            if (isLegacyFunnelsFilter(query.funnelsFilter as any)) {
                query.funnelsFilter = funnelsFilterToQuery(query.funnelsFilter as any)
            } else if (isLegacyFunnelsExclusion(query.funnelsFilter as any)) {
                query.funnelsFilter = {
                    ...query.funnelsFilter,
                    exclusions: query.funnelsFilter!.exclusions!.map((entity) =>
                        exlusionEntityToNode(entity as unknown as FunnelExclusionLegacy)
                    ),
                }
            }
        }

        if (query.kind === NodeKind.RetentionQuery && isLegacyRetentionFilter(query.retentionFilter as any)) {
            query.retentionFilter = retentionFilterToQuery(query.retentionFilter as any)
        }

        if (query.kind === NodeKind.PathsQuery && isLegacyPathsFilter(query.pathsFilter as any)) {
            query.pathsFilter = pathsFilterToQuery(query.pathsFilter as any)
        }

        if (query.kind === NodeKind.StickinessQuery && isLegacyStickinessFilter(query.stickinessFilter as any)) {
            const compareFilter = compareFilterToQuery(query.stickinessFilter as any)
            if (!isEmptyObject(compareFilter)) {
                query.compareFilter = compareFilter
            }
            delete (query.stickinessFilter as StickinessFilterLegacy).compare
            delete (query.stickinessFilter as StickinessFilterLegacy).compare_to

            // This has to come after compare, because it removes compare
            query.stickinessFilter = Object.fromEntries(
                Object.entries(query.stickinessFilter as StickinessFilter)
                    .filter(([k, _]) => STICKINESS_FILTER_PROPERTIES.has(k as keyof StickinessFilter))
                    .concat(Object.entries(stickinessFilterToQuery(query.stickinessFilter as any)))
            )
        }

        if (query.kind === NodeKind.LifecycleQuery && isLegacyLifecycleFilter(query.lifecycleFilter as any)) {
            query.lifecycleFilter = lifecycleFilterToQuery(query.lifecycleFilter as any)
        }

        /*
         * Breakdown
         */
        if ((query.kind === NodeKind.TrendsQuery || query.kind === NodeKind.FunnelsQuery) && 'breakdown' in query) {
            query.breakdownFilter = breakdownFilterToQuery(query.breakdown as any, query.kind === NodeKind.TrendsQuery)
            delete query.breakdown
        }

        return {
            ...node,
            attrs: {
                ...node.attrs,
                query: insightQuery,
            },
        }
    })
}
