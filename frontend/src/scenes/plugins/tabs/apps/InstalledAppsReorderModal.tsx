import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { useValues, useActions } from 'kea'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { LemonBadge, LemonButton } from '@posthog/lemon-ui'
import { PluginTypeWithConfig } from 'scenes/plugins/types'
import { SortEndHandler, SortableContainer, SortableElement } from 'react-sortable-hoc'
import { PluginImage } from 'scenes/plugins/plugin/PluginImage'

const MinimalAppView = ({ plugin, order }: { plugin: PluginTypeWithConfig; order: number }): JSX.Element => {
    return (
        <div
            className="flex gap-2 cursor-move border rounded p-2 items-center bg-light"
            // eslint-disable-next-line react/forbid-dom-props
            style={{
                zIndex: 999999,
            }}
        >
            <LemonBadge.Number count={order + 1} maxDigits={3} />
            <PluginImage plugin={plugin} size="small" />
            <span className="font-semibold">{plugin.name}</span>
        </div>
    )
}

const SortableAppView = SortableElement(MinimalAppView)

const SortableAppList = SortableContainer(({ children }: { children: React.ReactNode }) => {
    return <span className="flex flex-col gap-2">{children}</span>
})

export function InstalledAppsReorderModal(): JSX.Element {
    const { reorderModalOpen, sortableEnabledPlugins, temporaryOrder, pluginConfigsLoading } = useValues(pluginsLogic)
    const { closeReorderModal, setTemporaryOrder, cancelRearranging, savePluginOrders } = useActions(pluginsLogic)

    const onSortEnd: SortEndHandler = ({ oldIndex, newIndex }) => {
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
            <div className="space-y-4">
                <SortableAppList onSortEnd={onSortEnd} axis="y" lockAxis="y" lockToContainerEdges distance={5}>
                    {sortableEnabledPlugins.map((plugin, index) => (
                        <SortableAppView key={`item-${index}`} index={index} order={index} plugin={plugin} />
                    ))}
                </SortableAppList>
            </div>
        </LemonModal>
    )
}
