import { mergeAttributes, Node, NodeViewProps } from '@tiptap/core'
import { ReactNodeViewRenderer } from '@tiptap/react'
import { InsightShortId } from '~/types'
import { NodeWrapper } from 'scenes/notebooks/Nodes/NodeWrapper'
import { NotebookNodeType } from '~/types'
import { posthogNodePasteRule } from './utils'
import { urls } from 'scenes/urls'
import { Query } from '~/queries/Query/Query'
import { NodeKind } from '~/queries/schema'

const Component = (props: NodeViewProps): JSX.Element => {
    const href = `/insights/${props.node.attrs.id}`

    return (
        <NodeWrapper nodeType={NotebookNodeType.Insight} title="Insight" href={href} heightEstimate="16rem" {...props}>
            <Query query={{ kind: NodeKind.SavedInsightNode, shortId: props.node.attrs.id }} />
        </NodeWrapper>
    )
}

export const NotebookNodeInsight = Node.create({
    name: NotebookNodeType.Insight,
    group: 'block',
    atom: true,
    draggable: true,

    addAttributes() {
        return {
            id: '',
        }
    },

    parseHTML() {
        return [
            {
                tag: NotebookNodeType.Insight,
            },
        ]
    },

    renderHTML({ HTMLAttributes }) {
        return [NotebookNodeType.Insight, mergeAttributes(HTMLAttributes)]
    },

    addNodeView() {
        return ReactNodeViewRenderer(Component)
    },

    addPasteRules() {
        return [
            posthogNodePasteRule({
                find: urls.insightView('(.+)' as InsightShortId),
                type: this.type,
                getAttributes: async (match) => {
                    return { id: match[1] }
                },
            }),
        ]
    },
})
