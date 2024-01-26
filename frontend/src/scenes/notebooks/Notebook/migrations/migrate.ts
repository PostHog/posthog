import { JSONContent } from '@tiptap/core'

import {
    breakdownFilterToQuery,
    funnelsFilterToQuery,
    pathsFilterToQuery,
    retentionFilterToQuery,
    trendsFilterToQuery,
} from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import {
    isLegacyFunnelsFilter,
    isLegacyPathsFilter,
    isLegacyRetentionFilter,
    isLegacyTrendsFilter,
} from '~/queries/nodes/InsightQuery/utils/legacy'
import { InsightVizNode, NodeKind } from '~/queries/schema'
import { NotebookNodeType, NotebookType } from '~/types'

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

        return {
            ...node,
            attrs: {
                ...node.attrs,
                query: JSON.parse(node.attrs.query),
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
            query.trendsFilter = trendsFilterToQuery(query.trendsFilter as any)
        }

        if (query.kind === NodeKind.FunnelsQuery && isLegacyFunnelsFilter(query.funnelsFilter as any)) {
            query.funnelsFilter = funnelsFilterToQuery(query.funnelsFilter as any)
        }

        if (query.kind === NodeKind.RetentionQuery && isLegacyRetentionFilter(query.retentionFilter as any)) {
            query.retentionFilter = retentionFilterToQuery(query.retentionFilter as any)
        }

        if (query.kind === NodeKind.PathsQuery && isLegacyPathsFilter(query.pathsFilter as any)) {
            query.pathsFilter = pathsFilterToQuery(query.pathsFilter as any)
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
