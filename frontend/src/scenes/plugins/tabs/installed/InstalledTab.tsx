import React from 'react'
import { useValues } from 'kea'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { LogsDrawer } from '../../plugin/LogsDrawer'
import { PluginsSearch } from '../../PluginsSearch'
import { PluginsEmptyState } from './sections/PluginsEmptyState'
import { DisabledPluginSection } from './sections/DisabledPluginsSection'
import { UpgradeSection } from './sections/UpgradeSection'
import { EnabledPluginSection } from './sections/EnabledPluginsSection'
import { HistoryDrawer } from 'scenes/plugins/plugin/HistoryDrawer'

export function InstalledTab(): JSX.Element {
    const { installedPlugins } = useValues(pluginsLogic)

    if (installedPlugins.length === 0) {
        return <PluginsEmptyState />
    }

    return (
        <>
            <div>
                <PluginsSearch />
                <UpgradeSection />
                <EnabledPluginSection />
                <DisabledPluginSection />
            </div>
            <LogsDrawer />
            <HistoryDrawer />
        </>
    )
}
