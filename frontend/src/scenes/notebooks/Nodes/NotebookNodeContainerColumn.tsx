import { DndContext, closestCenter } from '@dnd-kit/core'
import { restrictToHorizontalAxis, restrictToParentElement } from '@dnd-kit/modifiers'
import { SortableContext, horizontalListSortingStrategy } from '@dnd-kit/sortable'
import { Node as TTNode, mergeAttributes, ReactNodeViewRenderer, NodeViewWrapper, NodeViewContent } from '@tiptap/react'

const NodeContainer = ({ node }): JSX.Element => {
    const { content: childNodes } = node.content

    const childIds = childNodes.map((n) => n.attrs.nodeId)

    console.log(childIds)

    return (
        <NodeViewWrapper className="container-container">
            <DndContext
                onDragEnd={() => {
                    console.log('moved item')
                }}
                collisionDetection={closestCenter}
                modifiers={[restrictToHorizontalAxis, restrictToParentElement]}
                onDragStart={() => console.log('emem')}
                onDragCancel={() => console.log('emem')}
                onDragMove={() => console.log('emem')}
                onDragOver={() => console.log('emem')}
            >
                <SortableContext items={childIds} strategy={horizontalListSortingStrategy}>
                    <NodeViewContent className="Notebook__container" />
                </SortableContext>
            </DndContext>
        </NodeViewWrapper>
    )
}

export default TTNode.create({
    name: 'container',
    group: 'block',
    // content: 'column{2,}',
    content: '(paragraph|block)*',
    isolating: true,
    selectable: true,
    atom: true,
    // draggable: true,

    renderHTML({ HTMLAttributes }) {
        return ['div', mergeAttributes(HTMLAttributes)]
    },

    addNodeView() {
        return ReactNodeViewRenderer(NodeContainer)
    },
})
