import React from 'react'
import { Button, Col, Empty, Row, Skeleton, Space, Tag } from 'antd'
import { CloudDownloadOutlined, SyncOutlined } from '@ant-design/icons'
import { useActions, useValues } from 'kea'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { Subtitle } from 'lib/components/PageHeader'
import { userLogic } from 'scenes/userLogic'
import { PluginLoading } from 'scenes/plugins/plugin/PluginLoading'
import { InstalledPlugin } from 'scenes/plugins/tabs/installed/InstalledPlugin'
import { PluginTab, PluginTypeWithConfig } from 'scenes/plugins/types'
import { SortableContainer, SortableElement, SortableHandle } from 'react-sortable-hoc'

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

export function InstalledTab(): JSX.Element {
    const { user } = useValues(userLogic)
    const {
        installedPlugins,
        enabledPlugins,
        disabledPlugins,
        loading,
        checkingForUpdates,
        hasNonSourcePlugins,
        pluginsNeedingUpdates,
        installedPluginUrls,
        updateStatus,
        rearranging,
        temporaryOrder,
    } = useValues(pluginsLogic)
    const {
        checkForUpdates,
        setPluginTab,
        rearrange,
        setTemporaryOrder,
        cancelRearranging,
        savePluginOrders,
    } = useActions(pluginsLogic)

    const upgradeButton =
        user?.plugin_access.install && hasNonSourcePlugins ? (
            <Button
                type="default"
                icon={pluginsNeedingUpdates.length > 0 ? <SyncOutlined /> : <CloudDownloadOutlined />}
                onClick={() => checkForUpdates(true)}
                loading={checkingForUpdates}
            >
                {checkingForUpdates
                    ? `Checking plugin ${Object.keys(updateStatus).length + 1} out of ${
                          Object.keys(installedPluginUrls).length
                      }`
                    : pluginsNeedingUpdates.length > 0
                    ? 'Check again'
                    : 'Check for updates'}
            </Button>
        ) : (
            <></>
        )

    const canRearrange = user?.plugin_access.configure && enabledPlugins.length > 1

    const rearrangingButtons = rearranging ? (
        <Space>
            <Button type="primary" loading={loading} onClick={() => savePluginOrders(temporaryOrder)}>
                Save Order
            </Button>
            <Button type="default" onClick={cancelRearranging}>
                Cancel
            </Button>
        </Space>
    ) : (
        <></>
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

    return (
        <div>
            {pluginsNeedingUpdates.length > 0 ? (
                <>
                    <Subtitle
                        subtitle={`Plugins to update (${pluginsNeedingUpdates.length})`}
                        buttons={<>{upgradeButton}</>}
                    />
                    <Row gutter={16} style={{ marginTop: 16 }}>
                        {pluginsNeedingUpdates.map((plugin) => (
                            <InstalledPlugin key={plugin.id} plugin={plugin} showUpdateButton />
                        ))}
                    </Row>
                </>
            ) : null}

            {enabledPlugins.length > 0 ? (
                <>
                    <Subtitle
                        subtitle={
                            rearranging ? (
                                <>
                                    Rearranging plugins{' '}
                                    <Tag color="red" style={{ fontWeight: 'normal', marginLeft: 10 }}>
                                        Unsaved
                                    </Tag>
                                </>
                            ) : (
                                `Enabled plugins (${enabledPlugins.length})`
                            )
                        }
                        buttons={
                            rearranging ? (
                                rearrangingButtons
                            ) : pluginsNeedingUpdates.length === 0 ? (
                                upgradeButton
                            ) : (
                                <></>
                            )
                        }
                    />
                    {canRearrange || rearranging ? (
                        <SortablePlugins useDragHandle onSortEnd={onSortEnd}>
                            {enabledPlugins.map((plugin, index) => (
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
                    ) : (
                        <Row gutter={16} style={{ marginTop: 16 }}>
                            {enabledPlugins.map((plugin, index) => (
                                <InstalledPlugin
                                    key={plugin.id}
                                    plugin={plugin}
                                    order={index + 1}
                                    maxOrder={enabledPlugins.length}
                                />
                            ))}
                        </Row>
                    )}
                </>
            ) : null}

            {disabledPlugins.length > 0 ? (
                <>
                    <Subtitle
                        subtitle={`Installed plugins (${disabledPlugins.length})`}
                        buttons={<>{enabledPlugins.length === 0 ? upgradeButton : null}</>}
                    />
                    <Row gutter={16} style={{ marginTop: 16 }}>
                        {disabledPlugins.map((plugin) => (
                            <InstalledPlugin key={plugin.id} plugin={plugin} />
                        ))}
                    </Row>
                </>
            ) : null}

            {installedPlugins.length === 0 ? (
                loading ? (
                    <>
                        <Subtitle subtitle="Enabled plugins" buttons={<Skeleton.Button style={{ width: 150 }} />} />
                        <PluginLoading />
                    </>
                ) : (
                    <>
                        <Subtitle subtitle="Installed plugins" />
                        <Row gutter={16} style={{ marginTop: 16 }}>
                            <Col span={24}>
                                <Empty description={<span>You haven't installed any plugins yet</span>}>
                                    <Button type="default" onClick={() => setPluginTab(PluginTab.Repository)}>
                                        Open the Plugin Repository
                                    </Button>
                                </Empty>
                            </Col>
                        </Row>
                    </>
                )
            ) : null}
        </div>
    )
}
