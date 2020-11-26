import React from 'react'
import { Button, Col, Row } from 'antd'
import { useActions, useValues } from 'kea'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { PlusOutlined } from '@ant-design/icons'
import { PluginCard, PluginLoading } from './PluginCard'
import { userLogic } from 'scenes/userLogic'
import { Subtitle } from 'lib/components/PageHeader'

export function InstalledPlugins(): JSX.Element {
    const { installedPlugins, loading } = useValues(pluginsLogic)
    const { setPluginTab } = useActions(pluginsLogic)
    const { user } = useValues(userLogic)

    return (
        <div>
            <Subtitle
                subtitle={
                    'Installed' + (!loading || installedPlugins.length > 0 ? ` (${installedPlugins.length})` : '')
                }
                buttons={
                    user?.plugin_access.install && (
                        <Button type="primary" icon={<PlusOutlined />} onClick={() => setPluginTab('available')}>
                            Install new plugin
                        </Button>
                    )
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
                                    pluginConfig={plugin.pluginConfig}
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
