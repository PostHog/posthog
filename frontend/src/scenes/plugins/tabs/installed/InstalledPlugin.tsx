import { PluginCard } from 'scenes/plugins/plugin/PluginCard'
import React from 'react'
import { PluginTypeWithConfig } from 'scenes/plugins/types'

export function InstalledPlugin({ plugin }: { plugin: PluginTypeWithConfig }): JSX.Element {
    return (
        <PluginCard
            key={plugin.id}
            pluginId={plugin.id}
            name={plugin.name}
            url={plugin.url}
            description={plugin.description}
            pluginType={plugin.plugin_type}
            pluginConfig={plugin.pluginConfig}
            upgrades={plugin.upgrades}
            error={plugin.error}
        />
    )
}
