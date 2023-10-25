import { useValues } from 'kea'
import { PluginsSearch } from 'scenes/plugins/PluginsSearch'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { PluginDrawer } from 'scenes/plugins/edit/PluginDrawer'
import { BatchExportsAlternativeWarning } from './components'
import { InstalledAppsReorderModal } from './InstalledAppsReorderModal'
import { AppsTable } from './AppsTable'
import { AppView } from './AppView'
import { PluginRepositoryEntry, PluginTypeWithConfig } from 'scenes/plugins/types'
import { PluginType } from '~/types'

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
                    title="Enabled Apps"
                    plugins={[...sortableEnabledPlugins, ...unsortableEnabledPlugins]}
                    loading={loading}
                    renderfn={renderfn}
                />
                <AppsTable
                    title="Available Apps"
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
