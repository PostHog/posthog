import { useValues } from 'kea'
import { PluginsSearch } from 'scenes/plugins/PluginsSearch'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { PluginDrawer } from 'scenes/plugins/edit/PluginDrawer'
import { BatchExportsAlternativeWarning } from './components'
import { InstalledAppsReorderModal } from './InstalledAppsReorderModal'
import { DestinationTable } from './DestinationTable'
import { AppView } from './AppView'
import { PluginRepositoryEntry, PluginTypeWithConfig } from 'scenes/plugins/types'
import { PluginType } from '~/types'
import { BatchExportsList } from 'scenes/batch_exports/BatchExportsListScene'

export function DestinationsTab(): JSX.Element {
    const { sortableEnabledPlugins, unsortableEnabledPlugins, filteredDisabledPlugins, loading } =
        useValues(pluginsLogic)

    const renderfn: (plugin: PluginTypeWithConfig | PluginType | PluginRepositoryEntry) => JSX.Element = (plugin) => (
        <AppView plugin={plugin} />
    )

    return (
        <>
            <div className="space-y-4">
                <BatchExportsAlternativeWarning />
                
                <BatchExportsList />

                <DestinationTable
                    title="Enabled Apps"
                    plugins={unsortableEnabledPlugins}
                    loading={loading}
                    renderfn={renderfn}
                />
                
                
            </div>
            <PluginDrawer />
            <InstalledAppsReorderModal />
        </>
    )
}
