import { JSONContent } from '@tiptap/core'

import { funnelsFilterToQuery } from '~/queries/nodes/InsightQuery/utils/filtersToQueryNode'
import { isLegacyFunnelsFilter } from '~/queries/nodes/InsightQuery/utils/legacy'
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

        const query = node.attrs.query as InsightVizNode
        const querySource = query.source

        if (querySource.kind === NodeKind.FunnelsQuery && isLegacyFunnelsFilter(querySource.funnelsFilter as any)) {
            querySource.funnelsFilter = funnelsFilterToQuery(querySource.funnelsFilter as any)
        }

        return {
            ...node,
            attrs: {
                ...node.attrs,
                query: query,
            },
        }
    })
}
