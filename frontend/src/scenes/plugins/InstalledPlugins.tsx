import React from 'react'
import { Button, Row } from 'antd'
import { useActions, useValues } from 'kea'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { PlusOutlined } from '@ant-design/icons'
import { PluginCard } from './PluginCard'

export function InstalledPlugins(): JSX.Element {
    const { installedPlugins, loading } = useValues(pluginsLogic)
    const { setPluginTab } = useActions(pluginsLogic)

    return (
        <div>
            <h2 className="oh-page-subtitle">Installed ({installedPlugins.length})</h2>
            <div className="text-right oh-spaced-bottom">
                <Button type="primary" icon={<PlusOutlined />} onClick={() => setPluginTab('available')}>
                    Install new plugin
                </Button>
            </div>
            {!loading && (
                <Row gutter={16}>
                    {installedPlugins.map((plugin) => {
                        return <PluginCard plugin={plugin} key={plugin.id} />
                    })}
                    {installedPlugins.length == 0 && <div>No Plugins Installed!</div>}
                </Row>
            )}
        </div>
    )
}
