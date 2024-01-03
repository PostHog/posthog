import { LemonButton, LemonDivider } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { IconCloudDownload, IconRefresh } from 'lib/lemon-ui/icons'
import { useMemo } from 'react'
import { canGloballyManagePlugins } from 'scenes/plugins/access'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { PluginsSearch } from 'scenes/plugins/PluginsSearch'
import { PluginRepositoryEntry, PluginTypeWithConfig } from 'scenes/plugins/types'
import { userLogic } from 'scenes/userLogic'

import { PluginType } from '~/types'

import { AdvancedInstallModal } from './AdvancedInstallModal'
import { AppManagementView } from './AppManagementView'
import { AppsTable } from './AppsTable'

export function AppsManagementTab(): JSX.Element {
    const { user } = useValues(userLogic)

    if (!canGloballyManagePlugins(user?.organization)) {
        return <></>
    }

    const { checkForUpdates, openAdvancedInstallModal } = useActions(pluginsLogic)

    const {
        installedPlugins,
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

    const renderfn: (plugin: PluginTypeWithConfig | PluginType | PluginRepositoryEntry) => JSX.Element = (plugin) => (
        <AppManagementView plugin={plugin} />
    )

    return (
        <>
            <div className="space-y-4">
                <div className="flex gap-2 items-center justify-between">
                    <PluginsSearch />

                    <div className="flex gap-2 items-center">
                        {hasUpdatablePlugins && (
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
                        <LemonButton type="secondary" onClick={openAdvancedInstallModal}>
                            Install app (advanced)
                        </LemonButton>
                    </div>
                </div>

                {filteredPluginsNeedingUpdates.length > 0 && (
                    <AppsTable
                        title="Apps to Update"
                        plugins={filteredPluginsNeedingUpdates}
                        loading={loading || checkingForUpdates}
                        renderfn={renderfn}
                    />
                )}

                <AppsTable title="Installed Apps" plugins={installedPlugins} loading={loading} renderfn={renderfn} />

                {canGloballyManagePlugins(user?.organization) && (
                    <>
                        <LemonDivider className="my-8" />

                        <AppsTable
                            title="Repository - Official"
                            plugins={officialPlugins}
                            loading={repositoryLoading}
                            renderfn={renderfn}
                        />
                        <AppsTable
                            title="Repository - Community"
                            plugins={communityPlugins}
                            loading={repositoryLoading}
                            renderfn={renderfn}
                        />
                    </>
                )}
            </div>
            <AdvancedInstallModal />
        </>
    )
}
