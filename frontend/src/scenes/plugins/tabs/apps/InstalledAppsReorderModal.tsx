import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { useValues, useActions } from 'kea'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { LemonBadge, LemonButton } from '@posthog/lemon-ui'
import { PluginTypeWithConfig } from 'scenes/plugins/types'
import { PluginImage } from 'scenes/plugins/plugin/PluginImage'
import { SortableContext, arrayMove, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { DndContext, DragEndEvent } from '@dnd-kit/core'
import { restrictToParentElement, restrictToVerticalAxis } from '@dnd-kit/modifiers'
import { CSS } from '@dnd-kit/utilities'

const MinimalAppView = ({ plugin, order }: { plugin: PluginTypeWithConfig; order: number }): JSX.Element => {
    const { setNodeRef, attributes, transform, transition, listeners, isDragging } = useSortable({ id: plugin.id })

    return (
        <div
            ref={setNodeRef}
            {...attributes}
            {...listeners}
            className="flex gap-2 cursor-move border rounded p-2 items-center bg-bg-light"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                position: 'relative',
                zIndex: isDragging ? 999999 : undefined,
                transform: CSS.Translate.toString(transform),
                transition,
            }}
        >
            <LemonBadge.Number count={order + 1} maxDigits={3} />
            <PluginImage plugin={plugin} size="small" />
            <span className="font-semibold">{plugin.name}</span>
        </div>
    )
}

export function InstalledAppsReorderModal(): JSX.Element {
    const { reorderModalOpen, sortableEnabledPlugins, temporaryOrder, pluginConfigsLoading } = useValues(pluginsLogic)
    const { closeReorderModal, setTemporaryOrder, cancelRearranging, savePluginOrders } = useActions(pluginsLogic)

    const onDragEnd = ({ active, over }: DragEndEvent): void => {
        const sortableEnabledPluginsIds = sortableEnabledPlugins.map((p) => p.id)

        if (over && active.id !== over.id) {
            const oldIndex = sortableEnabledPluginsIds.indexOf(Number(active.id))
            const newIndex = sortableEnabledPluginsIds.indexOf(Number(over.id))

            const newTemporaryOrder = arrayMove(sortableEnabledPlugins, oldIndex, newIndex).reduce(
                (acc, plugin, index) => {
                    return { ...acc, [plugin.id]: index + 1 }
                },
                {}
            )

            setTemporaryOrder(newTemporaryOrder, Number(active.id))
        }
    }

    const onClose = (): void => {
        cancelRearranging()
        closeReorderModal()
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
            <div className="flex flex-col gap-2">
                <DndContext onDragEnd={onDragEnd} modifiers={[restrictToVerticalAxis, restrictToParentElement]}>
                    <SortableContext
                        items={sortableEnabledPlugins.map((p) => p.id)}
                        strategy={verticalListSortingStrategy}
                    >
                        {sortableEnabledPlugins.map((plugin, index) => (
                            <MinimalAppView key={`item-${index}`} order={index} plugin={plugin} />
                        ))}
                    </SortableContext>
                </DndContext>
            </div>
        </LemonModal>
    )
}
