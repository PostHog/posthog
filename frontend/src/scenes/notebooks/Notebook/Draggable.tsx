import { closestCenter, DndContext } from '@dnd-kit/core'
import { restrictToHorizontalAxis, restrictToParentElement } from '@dnd-kit/modifiers'
import { horizontalListSortingStrategy, SortableContext, useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'

const Draggable = (): JSX.Element => {
    const childIds = ['1', '2', '3']

    console.log(childIds)

    return (
        <DndContext
            onDragEnd={({ active, over }) => {
                console.log('ended', active, over)
            }}
            collisionDetection={closestCenter}
            modifiers={[restrictToHorizontalAxis, restrictToParentElement]}
            onDragStart={() => console.log('started')}
            onDragCancel={() => console.log('canceled')}
            onDragMove={() => console.log('moved')}
            onDragOver={() => console.log('over')}
        >
            <SortableContext items={childIds} strategy={horizontalListSortingStrategy}>
                {/* <NodeViewContent className="Notebook__container" /> */}
                {childIds.map((id: string) => (
                    <DraggableItem key={id} id={id} />
                ))}
            </SortableContext>
        </DndContext>
    )
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

export default Draggable
