import { mergeAttributes, Node, NodeViewProps } from '@tiptap/core'
import { ReactNodeViewRenderer } from '@tiptap/react'
import { InsightShortId, NotebookMode } from '~/types'
import { NodeWrapper } from 'scenes/notebooks/Nodes/NodeWrapper'
import { NotebookNodeType } from '~/types'
import { posthogNodePasteRule } from './utils'
import { urls } from 'scenes/urls'
import { Query } from '~/queries/Query/Query'
import { NodeKind } from '~/queries/schema'
import { NotebookNodeCannotShare } from 'scenes/notebooks/Nodes/NotebookNodeCannotShare'

const Component = (props: NodeViewProps): JSX.Element => {
    const href = `/insights/${props.node.attrs.id}`
    const isShared = props.extension.options.viewMode === NotebookMode.Share

    return (
        <NodeWrapper
            nodeType={NotebookNodeType.Insight}
            title="Insight"
            href={href}
            heightEstimate={'16rem'}
            compact={isShared}
            {...props}
        >
            {isShared ? (
                <NotebookNodeCannotShare type={'insights'} />
            ) : (
                <Query query={{ kind: NodeKind.SavedInsightNode, shortId: props.node.attrs.id }} />
            )}
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
                getAttributes: (match) => {
                    return { id: match[1] }
                },
            }),
        ]
    },
})
