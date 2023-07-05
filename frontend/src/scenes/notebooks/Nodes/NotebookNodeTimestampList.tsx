import { mergeAttributes, Node, NodeViewProps } from '@tiptap/core'
import { NodeViewContent, NodeViewWrapper, ReactNodeViewRenderer } from '@tiptap/react'
import { NotebookNodeType } from '~/types'

const Component = (props: NodeViewProps): JSX.Element => {
    return (
        <NodeViewWrapper>
            <ul data-type={props.node.type.name}>
                <NodeViewContent />
            </ul>
        </NodeViewWrapper>
    )
}

export const NotebookNodeTimestampList = Node.create({
    name: NotebookNodeType.TimestampList,
    group: 'block',
    content: `${NotebookNodeType.TimestampItem}+`,

    parseHTML() {
        return [{ tag: `ul[data-type="${this.name}"]` }]
    },

    renderHTML({ HTMLAttributes }) {
        return ['ul', mergeAttributes(HTMLAttributes, { 'data-type': this.name })]
    },

    addNodeView() {
        return ReactNodeViewRenderer(Component)
    },
})
