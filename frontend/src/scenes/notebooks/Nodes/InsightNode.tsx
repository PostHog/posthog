import { mergeAttributes, Node } from '@tiptap/core'
import { ReactNodeViewRenderer } from '@tiptap/react'
import { BindLogic, useValues } from 'kea'
import { InsightContainer } from 'scenes/insights/InsightContainer'
import { insightLogic } from 'scenes/insights/insightLogic'
import { ItemMode } from '~/types'
import { NodeWrapper } from 'scenes/notebooks/Nodes/NodeWrapper'
import { NodeType } from 'scenes/notebooks/Nodes/types'

const Component = (): JSX.Element => {
    const logic = insightLogic({ dashboardItemId: 'new' })
    const { insightProps } = useValues(logic)

    return (
        <NodeWrapper className={NodeType.Insight}>
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

export const InsightNode = Node.create({
    name: 'posthogInsight',
    group: 'block',
    atom: true,
    draggable: true,

    addAttributes() {
        return {
            count: {
                default: 0,
            },
        }
    },

    parseHTML() {
        return [
            {
                tag: NodeType.Insight,
            },
        ]
    },

    renderHTML({ HTMLAttributes }) {
        return [NodeType.Insight, mergeAttributes(HTMLAttributes)]
    },

    addNodeView() {
        return ReactNodeViewRenderer(Component)
    },
})
