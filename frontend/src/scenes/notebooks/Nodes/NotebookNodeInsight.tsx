import { mergeAttributes, Node, nodePasteRule, NodeViewProps } from '@tiptap/core'
import { ReactNodeViewRenderer } from '@tiptap/react'
import { BindLogic, useValues } from 'kea'
import { InsightContainer } from 'scenes/insights/InsightContainer'
import { insightLogic } from 'scenes/insights/insightLogic'
import { InsightShortId, ItemMode } from '~/types'
import { NodeWrapper } from 'scenes/notebooks/Nodes/NodeWrapper'
import { NotebookNodeType } from 'scenes/notebooks/Nodes/types'
import { createUrlRegex } from './utils'
import { urls } from 'scenes/urls'

const Component = (props: NodeViewProps): JSX.Element => {
    const logic = insightLogic({ dashboardItemId: props.node.attrs.shortId })
    const { insightProps } = useValues(logic)

    const href = `/insights/${props.node.attrs.shortId}`

    return (
        <NodeWrapper className={NotebookNodeType.Insight} title="Insight" href={href} {...props}>
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
            nodePasteRule({
                find: createUrlRegex(urls.insightView('(.+)' as InsightShortId)),
                type: this.type,
                getAttributes: (match) => {
                    console.log({ match })
                    return { id: match[1] }
                },
            }),
        ]
    },
})
