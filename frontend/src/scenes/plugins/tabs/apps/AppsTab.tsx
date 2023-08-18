import { LemonTable, LemonButton, LemonDivider } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { IconCloudDownload, IconRefresh, IconUnfoldLess, IconUnfoldMore } from 'lib/lemon-ui/icons'
import { useMemo, useState } from 'react'
import { PluginsSearch } from 'scenes/plugins/PluginsSearch'
import { canGloballyManagePlugins, canInstallPlugins } from 'scenes/plugins/access'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { PluginRepositoryEntry, PluginTypeWithConfig } from 'scenes/plugins/types'
import { userLogic } from 'scenes/userLogic'
import { PluginType } from '~/types'
import { AdvancedInstallModal } from './AdvancedInstallModal'
import { AppView } from './AppView'
import { PluginDrawer } from 'scenes/plugins/edit/PluginDrawer'

export function AppsTab(): JSX.Element {
    const { user } = useValues(userLogic)
    const { checkForUpdates, openAdvancedInstallModal } = useActions(pluginsLogic)

    const {
        filteredEnabledPlugins,
        filteredDisabledPlugins,
        installedPluginUrls,
        filteredPluginsNeedingUpdates,
        loading,
        filteredUninstalledPlugins,
        repositoryLoading,
        pluginsNeedingUpdates,
        hasUpdatablePlugins,
        checkingForUpdates,
        updateStatus,
    } = useValues(pluginsLogic)

    const officialPlugins = useMemo(
        () => filteredUninstalledPlugins.filter((plugin) => plugin.maintainer === 'official'),
        [filteredUninstalledPlugins]
    )
    const communityPlugins = useMemo(
        () => filteredUninstalledPlugins.filter((plugin) => plugin.maintainer === 'community'),
        [filteredUninstalledPlugins]
    )

    return (
        <>
            <div className="space-y-4">
                <div className="flex gap-2 items-center justify-between">
                    <PluginsSearch />
                    <div className="flex gap-2 items-center">
                        {canInstallPlugins(user?.organization) && hasUpdatablePlugins && (
                            <LemonButton
                                type="secondary"
                                icon={pluginsNeedingUpdates.length > 0 ? <IconRefresh /> : <IconCloudDownload />}
                                onClick={(e) => {
                                    e.stopPropagation()
                                    checkForUpdates(true)
                                }}
                                loading={checkingForUpdates}
                            >
                                {checkingForUpdates
                                    ? `Checking app ${Object.keys(updateStatus).length + 1} out of ${
                                          Object.keys(installedPluginUrls).length
                                      }`
                                    : pluginsNeedingUpdates.length > 0
                                    ? 'Check again for updates'
                                    : 'Check for updates'}
                            </LemonButton>
                        )}

                        {canInstallPlugins(user?.organization) && (
                            <LemonButton type="secondary" onClick={openAdvancedInstallModal}>
                                Install app (advanced)
                            </LemonButton>
                        )}
                    </div>
                </div>

                {filteredPluginsNeedingUpdates.length > 0 && (
                    <AppsTable
                        title="Apps to Update"
                        plugins={filteredPluginsNeedingUpdates}
                        loading={checkingForUpdates}
                    />
                )}

                <AppsTable title="Enabled Apps" plugins={filteredEnabledPlugins} loading={loading} />
                <AppsTable title="Available Apps" plugins={filteredDisabledPlugins} loading={loading} />

                {canGloballyManagePlugins(user?.organization) && (
                    <>
                        <LemonDivider className="my-8" />

                        <AppsTable
                            title="Repository - Official"
                            plugins={officialPlugins}
                            loading={repositoryLoading}
                        />
                        <AppsTable
                            title="Repository - Community"
                            plugins={communityPlugins}
                            loading={repositoryLoading}
                        />
                    </>
                )}
            </div>
            <AdvancedInstallModal />
            <PluginDrawer />
        </>
    )
}

export function AppsTable({
    title = 'Apps',
    plugins,
    loading,
}: {
    title?: string
    plugins: (PluginTypeWithConfig | PluginType | PluginRepositoryEntry)[]
    loading: boolean
}): JSX.Element {
    const [expanded, setExpanded] = useState(true)
    const { searchTerm } = useValues(pluginsLogic)

    return (
        <LemonTable
            dataSource={expanded ? plugins : []}
            loading={loading}
            columns={[
                {
                    title: (
                        <>
                            <LemonButton
                                size="small"
                                status="stealth"
                                sideIcon={!expanded ? <IconUnfoldLess /> : <IconUnfoldMore />}
                                onClick={() => setExpanded(!expanded)}
                                className="-ml-2 mr-2"
                            />
                            {title}
                        </>
                    ),
                    key: 'app',
                    render: (_, plugin) => {
                        return <AppView plugin={plugin} />
                    },
                },
            ]}
            emptyState={
                !expanded ? (
                    <span className="flex gap-2 items-center">
                        <LemonButton size="small" onClick={() => setExpanded(true)}>
                            Show apps
                        </LemonButton>
                    </span>
                ) : searchTerm ? (
                    'No apps matching your search criteria'
                ) : (
                    'No apps found'
                )
            }
        />
    )
}
