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
import { PageHeader } from 'lib/components/PageHeader'

export function DestinationsTab(): JSX.Element {
    const { sortableEnabledPlugins, unsortableEnabledPlugins, filteredDisabledPlugins, loading } =
        useValues(pluginsLogic)

    const renderfn: (plugin: PluginTypeWithConfig | PluginType | PluginRepositoryEntry) => JSX.Element = (plugin) => (
        <AppView plugin={plugin} />
    )

    return (
        <>
            <PageHeader
                    title="Create new destination"
                />
            <div className="space-y-4">
                <div className="flex gap-2 items-center justify-between">
                    <PluginsSearch />
                </div>


                <DestinationTable
                    title="Streaming destinations"
                    plugins={filteredDisabledPlugins}
                    loading={loading}
                    renderfn={renderfn}
                />

                <DestinationTable
                    title="Batch destinations"
                    plugins={[
                        {name: "Bigquery", description: "Export PostHog events to Bigquery", }
                    ]}
                    loading={loading}
                    renderfn={renderfn}
                />

                
                
            </div>
            <PluginDrawer />
            <InstalledAppsReorderModal />
        </>
    )
}
