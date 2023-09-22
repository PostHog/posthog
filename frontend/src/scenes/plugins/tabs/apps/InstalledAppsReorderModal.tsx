import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { useValues, useActions } from 'kea'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { LemonBadge, LemonButton } from '@posthog/lemon-ui'
import { PluginTypeWithConfig } from 'scenes/plugins/types'
import { PluginImage } from 'scenes/plugins/plugin/PluginImage'
import { SortableContext, arrayMove, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { DndContext, DragEndEvent, closestCenter, closestCorners } from '@dnd-kit/core'
import { restrictToParentElement, restrictToVerticalAxis } from '@dnd-kit/modifiers'
import { CSS } from '@dnd-kit/utilities'
import { useEffect, useState } from 'react'
import { verticalSortableListCollisionDetection } from 'lib/sortable'

const MinimalAppView = ({ plugin, order }: { plugin: { id: number; name: string }; order: number }): JSX.Element => {
    const { setNodeRef, attributes, transform, transition, listeners, isDragging } = useSortable({ id: plugin.id })

    return (
        <div
            ref={setNodeRef}
            {...attributes}
            {...listeners}
            // className="flex gap-2 cursor-move border rounded p-2 items-center bg-bg-light"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                // position: 'relative',
                // zIndex: isDragging ? 999999 : undefined,
                transform: CSS.Translate.toString(transform),
                transition,
            }}
        >
            {/* <LemonBadge.Number count={order + 1} maxDigits={3} /> */}
            {/* <PluginImage plugin={plugin} size="small" /> */}
            <span className="font-semibold">{plugin.name}</span>
        </div>
    )
}

export function InstalledAppsReorderModal(): JSX.Element {
    const { reorderModalOpen, sortableEnabledPlugins, temporaryOrder, pluginConfigsLoading } = useValues(pluginsLogic)
    const { closeReorderModal, setTemporaryOrder, cancelRearranging, savePluginOrders } = useActions(pluginsLogic)

    // useEffect(() => {
    //     if (reorderModalOpen) {
    //         setTempOrder(sortableEnabledPlugins)
    //     }
    // }, [reorderModalOpen])

    // console.log(tempOrder.map((p) => p.name))

    const [items, setItems] = useState([
        { id: 'one', name: 'one' },
        { id: 'two', name: 'two' },
        { id: 'three', name: 'three' },
    ])

    const onClose = (): void => {
        cancelRearranging()
        closeReorderModal()
    }

    function handleDragEnd({ active, over }: DragEndEvent): void {
        const itemIds = items.map((item) => item.id)

        if (over && active.id !== over.id) {
            setItems((items) => {
                const oldIndex = itemIds.indexOf(active.id.toString())
                const newIndex = itemIds.indexOf(over.id.toString())

                return arrayMove(items, oldIndex, newIndex)
            })
        }
    }

    return (
        <LemonModal
            onClose={onClose}
            isOpen={reorderModalOpen}
            width={600}
            title="Re-order processing apps"
            description={
                <p>
                    The order of some apps is important as they are processed sequentially. You can{' '}
                    <b>drag and drop the apps below</b> to change their order.
                </p>
            }
            footer={
                <>
                    <LemonButton type="secondary" onClick={onClose}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        loading={pluginConfigsLoading}
                        type="primary"
                        onClick={() => savePluginOrders(temporaryOrder)}
                    >
                        Save order
                    </LemonButton>
                </>
            }
        >
            <DndContext collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
                <SortableContext items={items} strategy={verticalListSortingStrategy}>
                    {items.map((item) => (
                        <SortableItem key={item.id} plugin={item} />
                    ))}
                </SortableContext>
            </DndContext>
            {/* <div className="flex flex-col gap-2">
            <DndContext
                onDragEnd={onDragEnd}
                modifiers={[restrictToVerticalAxis, restrictToParentElement]}
                collisionDetection={closestCorners}
            >
                <SortableContext items={tempOrder} strategy={verticalListSortingStrategy}>
                    {tempOrder.map((tempOrder, index) => (
                        <MinimalAppView key={`item-${index}`} order={index} plugin={tempOrder} />
                    ))}
                </SortableContext>
            </DndContext>
            </div> */}
        </LemonModal>
    )
}

function SortableItem({ plugin }: { plugin: { id: string; name: string } }) {
    const { attributes, listeners, setNodeRef, transform, transition } = useSortable({ id: plugin.id })

    const style = {
        transform: CSS.Transform.toString(transform),
        transition,
    }

    return (
        <div ref={setNodeRef} style={style} {...attributes} {...listeners}>
            {plugin.name}
        </div>
    )
}
