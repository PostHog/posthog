import React from 'react'
import { useActions, useValues } from 'kea'
import { pluginsLogic } from '../pluginsLogic'
import { PluginLogs } from './PluginLogs'
import { Drawer } from 'antd'

export function LogsDrawer(): JSX.Element {
    const { showingLogsPlugin, lastShownLogsPlugin } = useValues(pluginsLogic)
    const { hidePluginLogs } = useActions(pluginsLogic)

    return (
        <Drawer
            visible={!!showingLogsPlugin}
            onClose={hidePluginLogs}
            width={'min(90vw, 80rem)'}
            title={`Viewing App Logs: ${lastShownLogsPlugin?.name}`}
            placement="left"
            destroyOnClose
        >
            {!!lastShownLogsPlugin?.pluginConfig.id && (
                <PluginLogs pluginConfigId={lastShownLogsPlugin.pluginConfig.id} />
            )}
        </Drawer>
    )
}
