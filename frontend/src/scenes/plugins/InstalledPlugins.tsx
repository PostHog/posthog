import React from 'react'
import { Button, Col, Row } from 'antd'
import { useActions, useValues } from 'kea'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { PlusOutlined } from '@ant-design/icons'
import { PluginCard, PluginLoading } from './PluginCard'

export function InstalledPlugins(): JSX.Element {
    const { installedPlugins, loading } = useValues(pluginsLogic)
    const { setPluginTab } = useActions(pluginsLogic)

    return (
        <div>
            <h2 className="oh-page-subtitle">Installed {!loading && <>({installedPlugins.length})</>}</h2>
            <div className="text-right oh-spaced-bottom">
                <Button type="primary" icon={<PlusOutlined />} onClick={() => setPluginTab('available')}>
                    Install new plugin
                </Button>
            </div>
            <Row gutter={16}>
                {!loading && (
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
                                />
                            )
                        })}
                        {installedPlugins.length == 0 && <Col span={24}>You don't have any plugins installed yet.</Col>}
                    </>
                )}
                {loading && <PluginLoading />}
            </Row>
        </div>
    )
}
