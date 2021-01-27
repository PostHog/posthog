import React from 'react'
import { PluginCard } from 'scenes/plugins/plugin/PluginCard'
import { PluginTypeWithConfig } from 'scenes/plugins/types'

export function InstalledPlugin({
    plugin,
    showUpdateButton,
    order,
    maxOrder,
    rearranging,
    DragColumn,
}: {
    plugin: PluginTypeWithConfig
    showUpdateButton?: boolean
    order?: number
    maxOrder?: number
    rearranging?: boolean
    DragColumn?: React.ComponentClass | React.FC
}): JSX.Element {
    return (
        <PluginCard
            key={plugin.id}
            plugin={plugin}
            showUpdateButton={showUpdateButton}
            order={order}
            maxOrder={maxOrder}
            rearranging={rearranging}
            DragColumn={DragColumn}
        />
    )
}
