import { useValues } from 'kea'
import { PluginDrawer } from 'scenes/plugins/edit/PluginDrawer'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { PluginsSearch } from 'scenes/plugins/PluginsSearch'
import { PluginRepositoryEntry, PluginTypeWithConfig } from 'scenes/plugins/types'

import { PluginType } from '~/types'

import { AppsTable } from './AppsTable'
import { AppView } from './AppView'
import { BatchExportsAlternativeWarning } from './components'
import { InstalledAppsReorderModal } from './InstalledAppsReorderModal'

export function AppsTab(): JSX.Element {
    const { sortableEnabledPlugins, unsortableEnabledPlugins, filteredDisabledPlugins, loading } =
        useValues(pluginsLogic)

    const renderfn: (plugin: PluginTypeWithConfig | PluginType | PluginRepositoryEntry) => JSX.Element = (plugin) => (
        <AppView plugin={plugin} />
    )

    return (
        <>
            <div className="space-y-4">
                <div className="flex gap-2 items-center justify-between">
                    <PluginsSearch />
                </div>

                <BatchExportsAlternativeWarning />

                <AppsTable
                    title="Enabled apps"
                    plugins={[...sortableEnabledPlugins, ...unsortableEnabledPlugins]}
                    loading={loading}
                    renderfn={renderfn}
                />
                <AppsTable
                    title="Available apps"
                    plugins={filteredDisabledPlugins}
                    loading={loading}
                    renderfn={renderfn}
                />
            </div>
            <PluginDrawer />
            <InstalledAppsReorderModal />
        </>
    )
}
