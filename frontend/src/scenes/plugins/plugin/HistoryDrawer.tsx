import React from 'react'
import { useActions, useValues } from 'kea'
import { pluginsLogic } from '../pluginsLogic'
import { Drawer } from 'antd'
import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { pluginActivityDescriber } from '../pluginActivityDescriptions'
import { ActivityScope } from 'lib/components/ActivityLog/humanizeActivity'

export function HistoryDrawer(): JSX.Element {
    const { showingHistoryPlugin } = useValues(pluginsLogic)
    const { hidePluginHistory } = useActions(pluginsLogic)

    return (
        <Drawer
            visible={!!showingHistoryPlugin}
            onClose={hidePluginHistory}
            width={'min(90vw, 80rem)'}
            title={`Activity History`}
            placement="left"
            destroyOnClose
        >
            <ActivityLog
                scope={ActivityScope.PLUGIN}
                id={showingHistoryPlugin?.pluginConfig.id}
                describer={pluginActivityDescriber}
            />
        </Drawer>
    )
}
