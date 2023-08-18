import { LemonTable, LemonButton, Link, LemonDivider, LemonTag } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import {
    IconCheckmark,
    IconCloudDownload,
    IconEllipsis,
    IconRefresh,
    IconSettings,
    IconUnfoldLess,
    IconUnfoldMore,
} from 'lib/lemon-ui/icons'
import { useMemo, useState } from 'react'
import { PluginsSearch } from 'scenes/plugins/PluginsSearch'
import { canGloballyManagePlugins, canInstallPlugins } from 'scenes/plugins/access'
import { PluginImage } from 'scenes/plugins/plugin/PluginImage'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'
import { PluginInstallationType, PluginRepositoryEntry, PluginTypeWithConfig } from 'scenes/plugins/types'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'
import { PluginType } from '~/types'
import { RepositoryTag } from './components'
import { SuccessRateBadge } from 'scenes/plugins/plugin/SuccessRateBadge'
import { AdvancedInstallModal } from './AdvancedInstallModal'
import { organizationLogic } from 'scenes/organizationLogic'
import { PluginsAccessLevel } from 'lib/constants'
import { Tooltip } from 'lib/lemon-ui/Tooltip'

export function AppsList(): JSX.Element {
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
        </>
    )
}

export function AppItem({
    plugin,
}: {
    plugin: PluginTypeWithConfig | PluginType | PluginRepositoryEntry
}): JSX.Element {
    const { installPlugin, editPlugin, toggleEnabled, updatePlugin } = useActions(pluginsLogic)
    const { installingPluginUrl, pluginsNeedingUpdates, pluginsUpdating, showAppMetricsForPlugin, loading } =
        useValues(pluginsLogic)

    const { currentOrganization } = useValues(organizationLogic)

    const pluginConfig = 'pluginConfig' in plugin ? plugin.pluginConfig : null
    const isConfigured = !!pluginConfig?.id

    return (
        <div className="flex justify-between items-center">
            <div className="flex items-center gap-2">
                <div className="shrink-0">
                    <PluginImage icon={plugin.icon} url={plugin.url} />
                </div>
                <div>
                    <div className="flex gap-2 items-center">
                        {pluginConfig && showAppMetricsForPlugin(plugin) && pluginConfig.id && (
                            <SuccessRateBadge
                                deliveryRate={pluginConfig.delivery_rate_24h ?? null}
                                pluginConfigId={pluginConfig.id}
                            />
                        )}
                        <Link
                            className="font-semibold truncate"
                            to={isConfigured ? urls.appMetrics(pluginConfig.id || '') : plugin.url}
                            target={!isConfigured ? 'blank' : undefined}
                            // TODO: onClick open configurator
                        >
                            {plugin.name}
                        </Link>

                        <RepositoryTag plugin={plugin} />

                        {'is_global' in plugin &&
                            plugin.is_global &&
                            !!currentOrganization &&
                            currentOrganization.plugins_access_level >= PluginsAccessLevel.Install && (
                                <Tooltip
                                    title={`This plugin is managed by the ${plugin.organization_name} organization`}
                                >
                                    <LemonTag type="success">Global</LemonTag>
                                </Tooltip>
                            )}
                    </div>
                    <div className="text-sm">{plugin.description}</div>
                </div>
            </div>

            <div className="flex gap-2 whitespace-nowrap justify-end">
                {'id' in plugin && pluginConfig ? (
                    <>
                        {!pluginConfig.enabled && isConfigured && (
                            <LemonButton
                                type="secondary"
                                size="small"
                                onClick={() =>
                                    toggleEnabled({
                                        id: pluginConfig.id,
                                        enabled: true,
                                    })
                                }
                            >
                                Enable
                            </LemonButton>
                        )}

                        {'updateStatus' in plugin && pluginsNeedingUpdates.find((x) => x.id === plugin.id) && (
                            <LemonButton
                                type="secondary"
                                size="small"
                                onClick={() => {
                                    plugin.updateStatus?.updated ? editPlugin(plugin.id) : updatePlugin(plugin.id)
                                }}
                                loading={pluginsUpdating.includes(plugin.id)}
                                icon={plugin.updateStatus?.updated ? <IconCheckmark /> : <IconCloudDownload />}
                            >
                                {plugin.updateStatus?.updated ? 'Updated' : 'Update'}
                            </LemonButton>
                        )}

                        <LemonButton
                            type="primary"
                            size="small"
                            icon={<IconSettings />}
                            onClick={() => editPlugin(plugin.id)}
                        >
                            Configure
                        </LemonButton>

                        <LemonMenu
                            items={[
                                {
                                    label: pluginConfig.enabled ? 'Disable' : 'Enable',
                                    status: pluginConfig.enabled ? 'danger' : 'primary',
                                    onClick: () =>
                                        isConfigured
                                            ? toggleEnabled({
                                                  id: pluginConfig.id,
                                                  enabled: !pluginConfig.enabled,
                                              })
                                            : editPlugin(plugin.id),
                                },
                            ]}
                            placement="left"
                        >
                            <LemonButton size="small" icon={<IconEllipsis />} />
                        </LemonMenu>
                    </>
                ) : (
                    <LemonButton
                        type="primary"
                        loading={loading && installingPluginUrl === plugin.url}
                        icon={<IconCloudDownload />}
                        size="small"
                        onClick={() =>
                            plugin.url ? installPlugin(plugin.url, PluginInstallationType.Repository) : undefined
                        }
                    >
                        Install
                    </LemonButton>
                )}
            </div>
        </div>
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
                        return <AppItem plugin={plugin} />
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
