import React from 'react'
import { Button, Col, Empty, Row, Skeleton } from 'antd'
import { CloudDownloadOutlined, SyncOutlined } from '@ant-design/icons'
import { useActions, useValues } from 'kea'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { Subtitle } from 'lib/components/PageHeader'
import { userLogic } from 'scenes/userLogic'
import { PluginLoading } from 'scenes/plugins/plugin/PluginLoading'
import { InstalledPlugin } from 'scenes/plugins/tabs/installed/InstalledPlugin'
import { PluginTab } from 'scenes/plugins/types'

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
    } = useValues(pluginsLogic)
    const { checkForUpdates, setPluginTab } = useActions(pluginsLogic)

    const upgradeButton =
        user?.plugin_access.install && hasNonSourcePlugins ? (
            <Button
                type="primary"
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
                    <Subtitle subtitle={`Enabled plugins (${enabledPlugins.length})`} buttons={<>{upgradeButton}</>} />
                    <Row gutter={16} style={{ marginTop: 16 }}>
                        {enabledPlugins.map((plugin) => (
                            <InstalledPlugin key={plugin.id} plugin={plugin} />
                        ))}
                    </Row>
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
