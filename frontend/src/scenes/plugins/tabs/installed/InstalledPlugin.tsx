import { PluginCard } from 'scenes/plugins/plugin/PluginCard'
import React from 'react'
import { PluginTypeWithConfig } from 'scenes/plugins/types'

export function InstalledPlugin({
    plugin,
    showUpdateButton,
}: {
    plugin: PluginTypeWithConfig
    showUpdateButton?: boolean
}): JSX.Element {
    return <PluginCard key={plugin.id} plugin={plugin} showUpdateButton={showUpdateButton} />
}
