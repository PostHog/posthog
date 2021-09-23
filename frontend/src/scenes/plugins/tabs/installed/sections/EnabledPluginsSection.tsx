import {
    CaretRightOutlined,
    CaretDownOutlined,
    CloseOutlined,
    SaveOutlined,
    OrderedListOutlined,
} from '@ant-design/icons'
import { Button, Col, Row, Space, Tag } from 'antd'
import { Subtitle } from 'lib/components/PageHeader'
import React from 'react'
import { useActions, useValues } from 'kea'
import { PluginSection, pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { InstalledPlugin } from '../InstalledPlugin'
import { canConfigurePlugins } from '../../../access'
import { userLogic } from 'scenes/userLogic'
import { SortableContainer, SortableElement, SortableHandle } from 'react-sortable-hoc'
import { PluginTypeWithConfig } from 'scenes/plugins/types'
import { Tooltip } from 'lib/components/Tooltip'

type HandleProps = { children?: JSX.Element }

const DragColumn = SortableHandle<HandleProps>(({ children }: HandleProps) => (
    <Col className="order-handle">{children}</Col>
))

const SortablePlugin = SortableElement(
    ({
        plugin,
        order,
        maxOrder,
        rearranging,
    }: {
        plugin: PluginTypeWithConfig
        order: number
        maxOrder: number
        rearranging: boolean
    }) => (
        <InstalledPlugin
            plugin={plugin}
            order={order}
            maxOrder={maxOrder}
            rearranging={rearranging}
            DragColumn={DragColumn}
        />
    )
)
const SortablePlugins = SortableContainer(({ children }: { children: React.ReactNode }) => {
    return (
        <Row gutter={16} style={{ marginTop: 16 }}>
            {children}
        </Row>
    )
})

export function EnabledPluginSection(): JSX.Element {
    const { user } = useValues(userLogic)

    const {
        rearrange,
        setTemporaryOrder,
        cancelRearranging,
        savePluginOrders,
        makePluginOrderSaveable,
        toggleSectionOpen,
    } = useActions(pluginsLogic)

    const {
        enabledPlugins,
        filteredEnabledPlugins,
        sortableEnabledPlugins,
        unsortableEnabledPlugins,
        rearranging,
        loading,
        temporaryOrder,
        pluginOrderSaveable,
        searchTerm,
        sectionsOpen,
    } = useValues(pluginsLogic)

    const canRearrange: boolean = canConfigurePlugins(user?.organization) && sortableEnabledPlugins.length > 1

    const rearrangingButtons = rearranging ? (
        <>
            <Button
                type="primary"
                icon={<SaveOutlined />}
                loading={loading}
                onClick={(e) => {
                    e.stopPropagation()
                    savePluginOrders(temporaryOrder)
                }}
                disabled={!pluginOrderSaveable}
            >
                Save order
            </Button>
            <Button
                type="default"
                icon={<CloseOutlined />}
                onClick={(e) => {
                    cancelRearranging()
                    e.stopPropagation()
                }}
            >
                Cancel
            </Button>
        </>
    ) : (
        <Tooltip
            title={
                enabledPlugins.length <= 1 ? (
                    'At least two plugins need to be enabled for reordering.'
                ) : (
                    <>
                        {!!searchTerm ? (
                            'Editing the order of plugins is disabled when searching.'
                        ) : (
                            <>
                                Order matters because event processing with plugins works like a pipe: the event is
                                processed by every enabled plugin <b>in sequence</b>.
                            </>
                        )}
                    </>
                )
            }
            placement="top"
        >
            <Button
                icon={<OrderedListOutlined />}
                onClick={(e) => {
                    e.stopPropagation()
                    rearrange()
                }}
                disabled={!!searchTerm || sortableEnabledPlugins.length <= 1}
            >
                Edit order
            </Button>
        </Tooltip>
    )

    const onSortEnd = ({ oldIndex, newIndex }: { oldIndex: number; newIndex: number }): void => {
        if (oldIndex === newIndex) {
            return
        }

        const move = (arr: PluginTypeWithConfig[], from: number, to: number): { id: number; order: number }[] => {
            const clone = [...arr]
            Array.prototype.splice.call(clone, to, 0, Array.prototype.splice.call(clone, from, 1)[0])
            return clone.map(({ id }, order) => ({ id, order: order + 1 }))
        }

        const movedPluginId: number = enabledPlugins[oldIndex]?.id

        const newTemporaryOrder: Record<number, number> = {}
        for (const { id, order } of move(enabledPlugins, oldIndex, newIndex)) {
            newTemporaryOrder[id] = order
        }

        if (!rearranging) {
            rearrange()
        }
        setTemporaryOrder(newTemporaryOrder, movedPluginId)
    }

    const EnabledPluginsHeader = (): JSX.Element => (
        <div className="plugins-installed-tab-section-header" onClick={() => toggleSectionOpen(PluginSection.Enabled)}>
            <Subtitle
                subtitle={
                    <>
                        {sectionsOpen.includes(PluginSection.Enabled) ? <CaretDownOutlined /> : <CaretRightOutlined />}
                        {` Enabled plugins (${filteredEnabledPlugins.length})`}
                        {rearranging && sectionsOpen.includes(PluginSection.Enabled) && (
                            <Tag color="red" style={{ fontWeight: 'normal', marginLeft: 10 }}>
                                Reordering in progress
                            </Tag>
                        )}
                    </>
                }
                buttons={<Space>{sectionsOpen.includes(PluginSection.Enabled) && rearrangingButtons}</Space>}
            />
        </div>
    )

    if (enabledPlugins.length === 0) {
        return (
            <>
                <EnabledPluginsHeader />
                {sectionsOpen.includes(PluginSection.Enabled) && <p style={{ margin: 10 }}>No plugins enabled.</p>}
            </>
        )
    }

    return (
        <>
            <EnabledPluginsHeader />
            {sectionsOpen.includes(PluginSection.Enabled) && (
                <>
                    {sortableEnabledPlugins.length === 0 && unsortableEnabledPlugins.length === 0 && (
                        <p style={{ margin: 10 }}>No plugins match your search.</p>
                    )}
                    {canRearrange || rearranging ? (
                        <>
                            {sortableEnabledPlugins.length > 0 && (
                                <>
                                    <SortablePlugins
                                        useDragHandle
                                        onSortEnd={onSortEnd}
                                        onSortOver={makePluginOrderSaveable}
                                    >
                                        {sortableEnabledPlugins.map((plugin, index) => (
                                            <SortablePlugin
                                                key={plugin.id}
                                                plugin={plugin}
                                                index={index}
                                                order={index + 1}
                                                maxOrder={enabledPlugins.length}
                                                rearranging={rearranging}
                                            />
                                        ))}
                                    </SortablePlugins>
                                </>
                            )}
                        </>
                    ) : (
                        <Row gutter={16} style={{ marginTop: 16 }}>
                            {sortableEnabledPlugins.length > 0 && (
                                <>
                                    {sortableEnabledPlugins.map((plugin, index) => (
                                        <InstalledPlugin
                                            key={plugin.id}
                                            plugin={plugin}
                                            order={index + 1}
                                            maxOrder={filteredEnabledPlugins.length}
                                        />
                                    ))}
                                </>
                            )}
                        </Row>
                    )}
                    {unsortableEnabledPlugins.map((plugin) => (
                        <InstalledPlugin
                            key={plugin.id}
                            plugin={plugin}
                            maxOrder={enabledPlugins.length}
                            rearranging={rearranging}
                            unorderedPlugin
                        />
                    ))}
                </>
            )}
        </>
    )
}
