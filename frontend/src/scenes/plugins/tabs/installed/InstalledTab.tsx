import React from 'react'
import { Alert, Button, Col, Empty, Row, Skeleton, Space } from 'antd'
import { CloudDownloadOutlined, SyncOutlined, SwapOutlined } from '@ant-design/icons'
import { useActions, useValues } from 'kea'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { Subtitle } from 'lib/components/PageHeader'
import { userLogic } from 'scenes/userLogic'
import { PluginLoading } from 'scenes/plugins/plugin/PluginLoading'
import { InstalledPlugin } from 'scenes/plugins/tabs/installed/InstalledPlugin'
import { PluginTab, PluginTypeWithConfig } from 'scenes/plugins/types'
import { SortableContainer, SortableElement } from 'react-sortable-hoc'

const SortablePlugin = SortableElement(
    ({ plugin, order, maxOrder }: { plugin: PluginTypeWithConfig; order: number; maxOrder: number }) => (
        <InstalledPlugin plugin={plugin} order={order} maxOrder={maxOrder} className="rearranging" />
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
    } = useValues(pluginsLogic)
    const { checkForUpdates, setPluginTab, rearrange, cancelRearranging } = useActions(pluginsLogic)

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
        ) : null

    const rearrangeButton =
        user?.plugin_access.install && enabledPlugins.length > 1 ? (
            <Button type="default" icon={<SwapOutlined style={{ transform: 'rotate(90deg)' }} />} onClick={rearrange}>
                Rearrange
            </Button>
        ) : null

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
                        subtitle={`Enabled plugins (${enabledPlugins.length})`}
                        buttons={
                            !rearranging ? (
                                <Space key="not-rearranging">
                                    {rearrangeButton}
                                    {upgradeButton}
                                </Space>
                            ) : (
                                <></>
                            )
                        }
                    />
                    {rearranging ? (
                        <Alert
                            message="Drag the plugins to set the ingestion order"
                            description={
                                <>
                                    <Space>
                                        <Button type="primary">Save Order</Button>
                                        <Button type="default" onClick={cancelRearranging}>
                                            Cancel
                                        </Button>
                                    </Space>
                                </>
                            }
                            onClose={cancelRearranging}
                            type="info"
                            showIcon
                            closable
                        />
                    ) : null}
                    {rearranging ? (
                        <SortablePlugins>
                            {enabledPlugins.map((plugin, index) => (
                                <SortablePlugin
                                    key={plugin.id}
                                    plugin={plugin}
                                    index={index}
                                    order={index + 1}
                                    maxOrder={enabledPlugins.length}
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
                        <Subtitle subtitle="Installed Plugins" />
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
