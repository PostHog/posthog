import { PluginCard } from 'scenes/plugins/plugin/PluginCard'
import React from 'react'
import { PluginTypeWithConfig } from 'scenes/plugins/types'

export function InstalledPlugin({
    plugin,
    showUpdateButton,
    order,
    maxOrder,
    className,
}: {
    plugin: PluginTypeWithConfig
    showUpdateButton?: boolean
    order?: number
    maxOrder?: number
    className?: string
}): JSX.Element {
    return (
        <PluginCard
            key={plugin.id}
            plugin={plugin}
            showUpdateButton={showUpdateButton}
            order={order}
            maxOrder={maxOrder}
            className={className}
        />
    )
}
