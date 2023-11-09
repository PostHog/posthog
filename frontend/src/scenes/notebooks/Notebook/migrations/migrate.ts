import { JSONContent } from '@tiptap/core'
import { NodeKind } from '~/queries/schema'
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
