import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { useValues, useActions } from 'kea'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { LemonBadge, LemonButton } from '@posthog/lemon-ui'
import { PluginTypeWithConfig } from 'scenes/plugins/types'
import { PluginImage } from 'scenes/plugins/plugin/PluginImage'
import { SortableContext, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { DndContext } from '@dnd-kit/core'
import { restrictToVerticalAxis } from '@dnd-kit/modifiers'
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

    const onSortEnd = ({ oldIndex, newIndex }: { oldIndex: number; newIndex: number }): void => {
        const cloned = [...sortableEnabledPlugins]
        const [removed] = cloned.splice(oldIndex, 1)
        cloned.splice(newIndex, 0, removed)

        const newTemporaryOrder = cloned.reduce((acc, plugin, index) => {
            return {
                ...acc,
                [plugin.id]: index + 1,
            }
        }, {})

        setTemporaryOrder(newTemporaryOrder, removed.id)
    }

    const onClose = (): void => {
        cancelRearranging()
        closeReorderModal()
    }

    const sortableEnabledPluginsIds = sortableEnabledPlugins.map((p) => p.id)

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
                <DndContext
                    onDragEnd={({ active, over }) => {
                        if (over && active.id !== over.id) {
                            onSortEnd({
                                oldIndex: sortableEnabledPluginsIds.indexOf(Number(active.id)),
                                newIndex: sortableEnabledPluginsIds.indexOf(Number(over.id)),
                            })
                        }
                    }}
                    modifiers={[restrictToVerticalAxis]}
                >
                    <SortableContext items={sortableEnabledPluginsIds} strategy={verticalListSortingStrategy}>
                        {sortableEnabledPlugins.map((plugin, index) => (
                            <MinimalAppView key={`item-${index}`} order={index} plugin={plugin} />
                        ))}
                    </SortableContext>
                </DndContext>

                {/* <SortableAppList onSortEnd={onSortEnd} axis="y" lockAxis="y" lockToContainerEdges distance={5}>
                    {sortableEnabledPlugins.map((plugin, index) => (
                        <SortableAppView key={`item-${index}`} index={index} order={index} plugin={plugin} />
                    ))}
                </SortableAppList> */}
            </div>
        </LemonModal>
    )
}
