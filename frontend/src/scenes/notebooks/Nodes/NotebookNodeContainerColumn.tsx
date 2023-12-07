import { DndContext, closestCenter } from '@dnd-kit/core'
import { restrictToHorizontalAxis, restrictToParentElement } from '@dnd-kit/modifiers'
import { SortableContext, horizontalListSortingStrategy, useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { Node as TTNode, mergeAttributes, ReactNodeViewRenderer, NodeViewWrapper, NodeViewContent } from '@tiptap/react'

const NodeContainer = ({ node }): JSX.Element => {
    const childIds = ['1', '2', '3']

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
                    {/* <NodeViewContent className="Notebook__container" /> */}
                    <div>
                        {childIds.map((id: string) => (
                            <DraggableItem key={id} id={id} />
                        ))}
                    </div>
                </SortableContext>
            </DndContext>
        </NodeViewWrapper>
    )
    // const { content: childNodes } = node.content

    // const childIds = childNodes.map((n) => n.attrs.nodeId)

    // console.log(childIds)

    // return (
    //     <NodeViewWrapper className="container-container">
    //         <DndContext
    //             onDragEnd={() => {
    //                 console.log('moved item')
    //             }}
    //             collisionDetection={closestCenter}
    //             modifiers={[restrictToHorizontalAxis, restrictToParentElement]}
    //             onDragStart={() => console.log('emem')}
    //             onDragCancel={() => console.log('emem')}
    //             onDragMove={() => console.log('emem')}
    //             onDragOver={() => console.log('emem')}
    //         >
    //             <SortableContext items={childIds} strategy={horizontalListSortingStrategy}>
    //                 {/* <NodeViewContent className="Notebook__container" /> */}
    //                 <div>
    //                     {childIds.map((id: string) => (
    //                         <DraggableItem key={id} id={id} />
    //                     ))}
    //                 </div>
    //             </SortableContext>
    //         </DndContext>
    //     </NodeViewWrapper>
    // )
}

const DraggableItem = ({ id }: { id: string }): JSX.Element => {
    const { setNodeRef, attributes: sortableAttributes, transform, transition, listeners } = useSortable({ id })

    return (
        <div
            contentEditable={false}
            ref={setNodeRef}
            {...sortableAttributes}
            {...listeners}
            style={{
                transform: CSS.Transform.toString(transform),
                transition,
            }}
        >
            This is {id}
        </div>
    )
}

export default TTNode.create({
    name: 'container',
    // group: 'block',
    // content: 'column{2,}',
    // content: '(paragraph|block)*',
    // isolating: true,
    // selectable: true,
    // atom: true,
    // draggable: false,
    group: 'block',
    atom: true,
    draggable: false,

    renderHTML({ HTMLAttributes }) {
        return ['div', mergeAttributes(HTMLAttributes)]
    },

    addNodeView() {
        return ReactNodeViewRenderer(NodeContainer)
    },
})
