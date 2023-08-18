import { LemonTable, LemonButton, Link, LemonDivider } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { IconCheckmark, IconCloudDownload, IconEllipsis, IconRefresh, IconSettings } from 'lib/lemon-ui/icons'
import { useMemo } from 'react'
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

export function AppsTable({
    title = 'Apps',
    plugins,
    loading,
}: {
    title?: string
    plugins: (PluginTypeWithConfig | PluginType | PluginRepositoryEntry)[]
    loading: boolean
}): JSX.Element {
    const { installPlugin, editPlugin, toggleEnabled, updatePlugin } = useActions(pluginsLogic)
    const { installingPluginUrl, pluginsNeedingUpdates, pluginsUpdating, showAppMetricsForPlugin } =
        useValues(pluginsLogic)

    return (
        <LemonTable
            dataSource={plugins}
            loading={loading}
            columns={[
                {
                    title: title,
                    key: 'app',
                    render: (_, plugin) => {
                        const isInstalled = 'pluginConfig' in plugin
                        const isConfigured = isInstalled && !!plugin.pluginConfig.id
                        return (
                            <div className="flex items-center gap-2">
                                <div className="shrink-0">
                                    <PluginImage icon={plugin.icon} url={plugin.url} />
                                </div>
                                <div>
                                    <div className="flex gap-2 items-center">
                                        {isInstalled && showAppMetricsForPlugin(plugin) && plugin.pluginConfig.id && (
                                            <SuccessRateBadge
                                                deliveryRate={plugin.pluginConfig.delivery_rate_24h ?? null}
                                                pluginConfigId={plugin.pluginConfig.id}
                                            />
                                        )}
                                        <Link
                                            className="font-semibold truncate"
                                            to={
                                                isConfigured
                                                    ? urls.appMetrics(plugin.pluginConfig.id || '')
                                                    : plugin.url
                                            }
                                            target={!isConfigured ? 'blank' : undefined}
                                            // TODO: onClick open configurator
                                        >
                                            {plugin.name}
                                        </Link>

                                        <RepositoryTag plugin={plugin} />
                                    </div>
                                    <div className="text-sm">{plugin.description}</div>
                                </div>
                            </div>
                        )
                    },
                },
                {
                    key: 'actions',
                    width: 0,

                    render: (_, plugin) => {
                        if ('pluginConfig' in plugin) {
                            const isConfigured = !!plugin.pluginConfig.id
                            return (
                                <div className="flex gap-2 whitespace-nowrap justify-end">
                                    {!plugin.pluginConfig.enabled && isConfigured && (
                                        <LemonButton
                                            type="secondary"
                                            size="small"
                                            onClick={() =>
                                                toggleEnabled({
                                                    id: plugin.pluginConfig.id,
                                                    enabled: true,
                                                })
                                            }
                                        >
                                            Enable
                                        </LemonButton>
                                    )}

                                    {pluginsNeedingUpdates.find((x) => x.id === plugin.id) && (
                                        <LemonButton
                                            type="secondary"
                                            size="small"
                                            onClick={() => {
                                                plugin.updateStatus?.updated
                                                    ? editPlugin(plugin.id)
                                                    : updatePlugin(plugin.id)
                                            }}
                                            loading={pluginsUpdating.includes(plugin.id)}
                                            icon={
                                                plugin.updateStatus?.updated ? <IconCheckmark /> : <IconCloudDownload />
                                            }
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
                                                label: plugin.pluginConfig.enabled ? 'Disable' : 'Enable',
                                                status: plugin.pluginConfig.enabled ? 'danger' : 'primary',
                                                onClick: () =>
                                                    isConfigured
                                                        ? toggleEnabled({
                                                              id: plugin.pluginConfig.id,
                                                              enabled: !plugin.pluginConfig.enabled,
                                                          })
                                                        : editPlugin(plugin.id),
                                            },
                                        ]}
                                        placement="left"
                                    >
                                        <LemonButton size="small" icon={<IconEllipsis />} />
                                    </LemonMenu>
                                </div>
                            )
                        }

                        return (
                            <LemonButton
                                type="primary"
                                loading={loading && installingPluginUrl === plugin.url}
                                icon={<IconCloudDownload />}
                                size="small"
                                onClick={() =>
                                    plugin.url
                                        ? installPlugin(plugin.url, PluginInstallationType.Repository)
                                        : undefined
                                }
                            >
                                Install
                            </LemonButton>
                        )
                    },
                },
            ]}
        />
    )
}
