import { mergeAttributes, Node, NodeViewProps } from '@tiptap/core'
import { ReactNodeViewRenderer } from '@tiptap/react'
import { BindLogic, useValues } from 'kea'
import { InsightContainer } from 'scenes/insights/InsightContainer'
import { insightLogic } from 'scenes/insights/insightLogic'
import { InsightShortId, ItemMode } from '~/types'
import { NodeWrapper } from 'scenes/notebooks/Nodes/NodeWrapper'
import { NotebookNodeType } from 'scenes/notebooks/Nodes/types'
import { posthogNodePasteRule } from './utils'
import { urls } from 'scenes/urls'

const Component = (props: NodeViewProps): JSX.Element => {
    const logic = insightLogic({ dashboardItemId: props.node.attrs.id })
    const { insightProps } = useValues(logic)

    const href = `/insights/${props.node.attrs.id}`

    return (
        <NodeWrapper nodeType={NotebookNodeType.Insight} title="Insight" href={href} heightEstimate="16rem" {...props}>
            <BindLogic logic={insightLogic} props={insightProps}>
                <div className="insights-container" data-attr="insight-view">
                    <InsightContainer
                        insightMode={ItemMode.Sharing}
                        disableCorrelationTable
                        disableHeader
                        disableLastComputation
                        disableTable
                    />
                </div>
            </BindLogic>
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
