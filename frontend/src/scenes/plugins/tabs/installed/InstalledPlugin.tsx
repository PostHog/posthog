import { PluginCard } from 'scenes/plugins/plugin/PluginCard'
import React from 'react'
import { PluginTypeWithConfig } from 'scenes/plugins/types'

export function InstalledPlugin({
    plugin,
    showUpdateButton,
    order,
    maxOrder,
}: {
    plugin: PluginTypeWithConfig
    showUpdateButton?: boolean
    order?: number
    maxOrder?: number
}): JSX.Element {
    return (
        <PluginCard
            key={plugin.id}
            plugin={plugin}
            showUpdateButton={showUpdateButton}
            order={order}
            maxOrder={maxOrder}
        />
    )
}
