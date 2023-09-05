import { JSONContent } from '@tiptap/core'
import { NodeKind } from '~/queries/schema'
import { NotebookNodeType, NotebookType } from '~/types'

export const NOTEBOOKS_VERSION = '1'

export function migrate(notebook: NotebookType): NotebookType {
    let content = notebook.content.content

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
