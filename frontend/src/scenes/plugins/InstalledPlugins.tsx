import React from 'react'
import { Col, Row } from 'antd'
import { useValues } from 'kea'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { PluginCard, PluginLoading } from './PluginCard'
import { Subtitle } from 'lib/components/PageHeader'

export function InstalledPlugins(): JSX.Element {
    const { installedPlugins, loading } = useValues(pluginsLogic)

    return (
        <div>
            <Subtitle
                subtitle={
                    'Installed Plugins' +
                    (!loading || installedPlugins.length > 0 ? ` (${installedPlugins.length})` : '')
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
