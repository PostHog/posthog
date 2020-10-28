import React from 'react'
import { Button } from 'antd'
import { useActions, useValues } from 'kea'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { PlusOutlined } from '@ant-design/icons'
import { PluginCard } from './PluginCard'

export function InstalledPlugins(): JSX.Element {
    const { installedPlugins, loading } = useValues(pluginsLogic)
    const { setPluginTab } = useActions(pluginsLogic)

    return (
        <div>
            <div className="text-right oh-spaced-bottom">
                <Button type="primary" icon={<PlusOutlined />} onClick={() => setPluginTab('available')}>
                    Install new plugin
                </Button>
            </div>
            {!loading && (
                <>
                    {installedPlugins.map((plugin) => {
                        return <PluginCard plugin={plugin} key={plugin.id} />
                    })}
                    {installedPlugins.length == 0 && <div>No Plugins Installed!</div>}
                </>
            )}
        </div>
    )
}
