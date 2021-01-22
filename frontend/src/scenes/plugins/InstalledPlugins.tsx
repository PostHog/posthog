import React from 'react'
import { Button, Col, Row } from 'antd'
import { CloudDownloadOutlined } from '@ant-design/icons'
import { useActions, useValues } from 'kea'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { PluginCard, PluginLoading } from './PluginCard'
import { Subtitle } from 'lib/components/PageHeader'
import { userLogic } from 'scenes/userLogic'

export function InstalledPlugins(): JSX.Element {
    const { user } = useValues(userLogic)
    const { installedPlugins, loading, checkingForUpgrades, hasNonSourcePlugins } = useValues(pluginsLogic)
    const { checkForUpgrades } = useActions(pluginsLogic)

    return (
        <div>
            <Subtitle
                subtitle={
                    'Installed Plugins' +
                    (!loading || installedPlugins.length > 0 ? ` (${installedPlugins.length})` : '')
                }
                buttons={
                    <>
                        {user.plugin_access.install && hasNonSourcePlugins && (
                            <Button
                                type="primary"
                                icon={<CloudDownloadOutlined />}
                                onClick={checkForUpgrades}
                                loading={checkingForUpgrades}
                                disabled={checkingForUpgrades}
                            >
                                Check for Upgrades
                            </Button>
                        )}
                    </>
                }
            />
            <Row gutter={16} style={{ marginTop: 16 }}>
                {(!loading || installedPlugins.length > 0) && (
                    <>
                        {installedPlugins.map((plugin) => {
                            return (
                                <PluginCard
                                    key={plugin.id}
                                    pluginId={plugin.id}
                                    name={plugin.name}
                                    url={plugin.url}
                                    description={plugin.description}
                                    pluginType={plugin.plugin_type}
                                    pluginConfig={plugin.pluginConfig}
                                    upgrades={plugin.upgrades}
                                    error={plugin.error}
                                />
                            )
                        })}
                        {installedPlugins.length == 0 && <Col span={24}>You don't have any plugins installed yet.</Col>}
                    </>
                )}
                {loading && installedPlugins.length === 0 && <PluginLoading />}
            </Row>
        </div>
    )
}
