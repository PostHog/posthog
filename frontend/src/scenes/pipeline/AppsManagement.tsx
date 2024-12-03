import { IconDownload, IconLock, IconRedo, IconTrash, IconUnlock } from '@posthog/icons'
import { LemonBanner, LemonDialog, LemonDivider, LemonMenu, LemonTable, LemonTag, Tooltip } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { Link } from 'lib/lemon-ui/Link'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { PluginInstallationType, PluginType } from '~/types'

import { AppCode } from './AppCode'
import { appsManagementLogic } from './appsManagementLogic'
import { SourcePluginKind } from './sourceAppInitialCode'
import { RenderApp } from './utils'

export const scene: SceneExport = {
    component: AppsManagement,
    logic: appsManagementLogic,
}

export function AppsManagement(): JSX.Element {
    // NOTE: We don't want to unmount appsManagementLogic once it's mounted. This is a memoization technique for
    // `checkForUpdates`, as otherwise leaving the page and coming back to it would result in us checking for updates
    // each time. Normally such a hack is a bit of a smell, but this is a staff-only page, so totally fine.
    appsManagementLogic.mount()

    const {
        canInstallPlugins,
        canGloballyManagePlugins,
        missingGlobalPlugins,
        shouldBeGlobalPlugins,
        shouldNotBeGlobalPlugins,
        globalPlugins,
        localPlugins,
        inlinePlugins,
        pluginsLoading,
    } = useValues(appsManagementLogic)
    const { isDev, isCloudOrDev } = useValues(preflightLogic)

    if (!canInstallPlugins || !canGloballyManagePlugins) {
        return <>You don't have permission to manage apps.</>
    }

    return (
        <div className="pipeline-apps-management-scene">
            {/* When plugins are still loading we don't know yet if any apps are out of sync
            with the global state, so skip this section for smooter user experience */}
            {isCloudOrDev &&
                !pluginsLoading &&
                (missingGlobalPlugins.length > 0 ||
                    shouldBeGlobalPlugins.length > 0 ||
                    shouldNotBeGlobalPlugins.length > 0) && <OutOfSyncApps />}
            <h2>Manual installation</h2>
            <InstallFromUrl />
            {isDev && <InstallLocalApp />}
            <InstallSourceApp />

            <LemonDivider className="my-6" />

            <h2>Installed apps</h2>
            <AppsToUpdate />
            {globalPlugins && (
                <>
                    <h3 className="mt-3">Global apps</h3>
                    <p>These apps can be used in all organizations.</p>
                    <AppsTable plugins={globalPlugins} />
                </>
            )}

            {localPlugins && (
                <>
                    <h3 className="mt-3">Local apps</h3>
                    <p>These apps can only be used by this organization, or ones with an existing plugin config.</p>
                    <AppsTable plugins={localPlugins} />
                </>
            )}

            {inlinePlugins && (
                <>
                    <h3 className="mt-3">Inline plugins</h3>
                    <p>These plugins are inlined into plugin-server code, any updates should be done there.</p>
                    <InlinePluginsTable plugins={inlinePlugins} />
                </>
            )}
        </div>
    )
}

type RenderAppsTable = {
    plugins: PluginType[]
}

function AppsToUpdate(): JSX.Element {
    const { updatablePlugins, pluginsNeedingUpdates, checkingForUpdates } = useValues(appsManagementLogic)
    const { checkForUpdates } = useActions(appsManagementLogic)

    return (
        <>
            {updatablePlugins && (
                <LemonButton
                    type="secondary"
                    icon={<IconRedo />}
                    onClick={checkForUpdates}
                    loading={checkingForUpdates}
                >
                    {checkingForUpdates
                        ? `Checking ${Object.keys(updatablePlugins).length} apps for updates`
                        : // we by default already check all apps for updates on initial load
                          'Check again for updates'}
                </LemonButton>
            )}
            {pluginsNeedingUpdates.length > 0 && (
                <>
                    <h3 className="mt-3">Apps to update</h3>
                    <p>These apps have newer commits in the repository they link to.</p>
                    <AppsTable plugins={pluginsNeedingUpdates} />
                </>
            )}
        </>
    )
}

function AppsTable({ plugins }: RenderAppsTable): JSX.Element {
    const { unusedPlugins } = useValues(appsManagementLogic)
    const { uninstallPlugin, patchPlugin, updatePlugin } = useActions(appsManagementLogic)

    const onClickUninstall = (pluginId: number): void => {
        LemonDialog.open({
            title: 'Are you sure you wish to uninstall this app completely?',
            primaryButton: {
                children: 'Uninstall',
                type: 'secondary',
                status: 'danger',
                onClick: () => uninstallPlugin(pluginId),
            },
            secondaryButton: {
                children: 'Cancel',
            },
        })
    }

    const data = plugins.map((plugin) => ({ ...plugin, key: plugin.id }))
    return (
        <>
            <LemonTable
                dataSource={data}
                columns={[
                    {
                        width: 60,
                        render: function RenderAppInfo(_, plugin) {
                            return <RenderApp plugin={plugin as PluginType} />
                        },
                    },
                    {
                        title: 'Name',
                        render: function RenderName(_, plugin) {
                            return (
                                <>
                                    <div className="flex gap-2 items-center">
                                        <span className="font-semibold truncate">{plugin.name}</span>
                                        {plugin.latest_tag && plugin.tag && plugin.latest_tag !== plugin.tag && (
                                            <Link
                                                to={plugin.url + '/compare/' + plugin.tag + '...' + plugin.latest_tag}
                                            >
                                                <LemonTag type="completion">See update diff</LemonTag>
                                            </Link>
                                        )}
                                    </div>
                                    <div className="text-sm">{plugin.description}</div>
                                </>
                            )
                        },
                    },
                    {
                        title: 'Capabilities',
                        width: '30%',
                        render: function RenderCapabilities(_, plugin) {
                            // TODO: use labels by app type once we get rid of jobs and scheduled tasks
                            return (
                                <>
                                    <div className="text-sm">
                                        Methods: {JSON.stringify(plugin.capabilities?.methods)}
                                    </div>
                                    <div className="text-sm">Jobs: {JSON.stringify(plugin.capabilities?.jobs)}</div>
                                    <div className="text-sm">
                                        Scheduled tasks: {JSON.stringify(plugin.capabilities?.scheduled_tasks)}
                                    </div>
                                </>
                            )
                        },
                    },
                    {
                        title: 'Actions',
                        width: 240,
                        align: 'right',
                        render: function RenderAccess(_, plugin) {
                            return (
                                <div className="flex items-center gap-2 justify-end">
                                    {plugin.latest_tag && plugin.tag != plugin.latest_tag && (
                                        <LemonButton
                                            type="secondary"
                                            size="small"
                                            icon={<IconDownload />}
                                            onClick={() => updatePlugin(plugin.id)}
                                        >
                                            Update
                                        </LemonButton>
                                    )}
                                    {plugin.is_global ? (
                                        <Tooltip
                                            title={
                                                <>
                                                    This app can currently be used by other organizations in this
                                                    instance of PostHog. This action will <b>disable and hide it</b> for
                                                    all organizations that do not have an existing pluginconfig.
                                                </>
                                            }
                                        >
                                            <LemonButton
                                                type="secondary"
                                                size="small"
                                                icon={<IconLock />}
                                                onClick={() => patchPlugin(plugin.id, { is_global: false })}
                                            >
                                                Make local
                                            </LemonButton>
                                        </Tooltip>
                                    ) : (
                                        <Tooltip
                                            title={
                                                <>
                                                    This action will mark this app as installed for{' '}
                                                    <b>all organizations</b> in this instance of PostHog.
                                                </>
                                            }
                                        >
                                            <LemonButton
                                                type="secondary"
                                                size="small"
                                                icon={<IconUnlock />}
                                                onClick={() => patchPlugin(plugin.id, { is_global: true })}
                                            >
                                                Make global
                                            </LemonButton>
                                        </Tooltip>
                                    )}
                                    <LemonButton
                                        type="secondary"
                                        status="danger"
                                        size="small"
                                        icon={<IconTrash />}
                                        disabledReason={
                                            unusedPlugins.includes(plugin.id) ? undefined : 'This app is still in use.'
                                        }
                                        data-attr="plugin-uninstall"
                                        onClick={() => onClickUninstall(plugin.id)}
                                    >
                                        Uninstall
                                    </LemonButton>
                                </div>
                            )
                        },
                    },
                ]}
                expandable={{
                    expandedRowRender: function Render(plugin: PluginType) {
                        return <AppCode pluginId={plugin.id} pluginType={plugin.plugin_type} />
                    },
                }}
            />
        </>
    )
}

function InlinePluginsTable({ plugins }: RenderAppsTable): JSX.Element {
    const data = plugins.map((plugin) => ({ ...plugin, key: plugin.id }))
    return (
        <>
            <LemonTable
                dataSource={data}
                columns={[
                    {
                        title: 'Name',
                        render: function RenderName(_, plugin) {
                            return (
                                <>
                                    <div className="flex gap-2 items-center">
                                        <span className="font-semibold truncate">{plugin.name}</span>
                                    </div>
                                    <div className="text-sm">{plugin.description}</div>
                                </>
                            )
                        },
                    },
                    {
                        title: 'Capabilities',
                        width: '30%',
                        render: function RenderCapabilities(_, plugin) {
                            // TODO: use labels by app type once we get rid of jobs and scheduled tasks
                            return (
                                <>
                                    <div className="text-sm">
                                        Methods: {JSON.stringify(plugin.capabilities?.methods)}
                                    </div>
                                    <div className="text-sm">Jobs: {JSON.stringify(plugin.capabilities?.jobs)}</div>
                                    <div className="text-sm">
                                        Scheduled tasks: {JSON.stringify(plugin.capabilities?.scheduled_tasks)}
                                    </div>
                                </>
                            )
                        },
                    },
                    {
                        title: 'Global',
                        render: function RenderGlobal(_, plugin) {
                            return <span>{plugin.is_global ? 'Yes' : 'No'}</span>
                        },
                    },
                ]}
            />
        </>
    )
}

function OutOfSyncApps(): JSX.Element {
    const { shouldNotBeGlobalPlugins, shouldBeGlobalPlugins } = useValues(appsManagementLogic)

    return (
        <>
            <h2>Out-of-sync global apps</h2>
            <LemonBanner type="warning">
                This PostHog Cloud instance is currently out of sync with the GLOBAL_PLUGINS list.
            </LemonBanner>
            <MissingGlobalPlugins />

            {shouldNotBeGlobalPlugins && (
                <>
                    <h3 className="mt-3">Apps that should NOT be global</h3>
                    <p>These apps should NOT be global according to repo.</p>
                    <AppsTable plugins={shouldNotBeGlobalPlugins} />
                </>
            )}

            {shouldBeGlobalPlugins && (
                <>
                    <h3 className="mt-3">Apps that SHOULD be global</h3>
                    <p>These already installed apps should be global according to repo.</p>
                    <AppsTable plugins={shouldBeGlobalPlugins} />
                </>
            )}
            <LemonDivider className="my-6" />
        </>
    )
}

function MissingGlobalPlugins(): JSX.Element {
    const { missingGlobalPlugins, pluginsLoading, installingPluginUrl } = useValues(appsManagementLogic)
    const { installPlugin } = useActions(appsManagementLogic)

    if (missingGlobalPlugins.length === 0) {
        return <></>
    }
    const data = missingGlobalPlugins.map((url: string) => ({ url }))
    return (
        <>
            <h3 className="mt-3">Missing global apps</h3>
            <p>These plugins are defined in the GLOBAL_PLUGINS list, but are not installed on this instance.</p>
            <LemonTable
                dataSource={data}
                columns={[
                    {
                        title: 'URL',
                        key: 'url',
                        render: function RenderUrl(_, { url }) {
                            return (
                                <Link to={url} target="_blank">
                                    {url}
                                </Link>
                            )
                        },
                    },
                    {
                        title: 'Actions',
                        width: 0,
                        align: 'right',
                        render: function RenderInstallButton(_, { url }) {
                            return (
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    loading={pluginsLoading && installingPluginUrl === url}
                                    onClick={() => installPlugin(PluginInstallationType.Repository, url)}
                                    id={`install-plugin-${url}`}
                                >
                                    Install
                                </LemonButton>
                            )
                        },
                    },
                ]}
            />
        </>
    )
}

function InstallFromUrl(): JSX.Element {
    // On cloud we only allow public PostHog org repository plugins
    // On self-hosted we allow any repo, could be private
    const { isCloudOrDev } = useValues(preflightLogic)
    const { pluginUrl } = useValues(appsManagementLogic)
    const { setPluginUrl, installPlugin } = useActions(appsManagementLogic)

    const cloudRequiredPrefix = 'https://github.com/PostHog/'
    let disabledReason = !pluginUrl ? 'Please enter a url' : undefined
    if (isCloudOrDev) {
        disabledReason = !pluginUrl.startsWith(cloudRequiredPrefix) ? 'Please enter a PostHog org repo url' : undefined
    }

    return (
        <>
            <h3 className="mt-3">Install from GitHub</h3>
            <p>
                {isCloudOrDev ? (
                    <>
                        Only PostHog organization repositories are allowed, i.e. starting with{' '}
                        <Link to={cloudRequiredPrefix} target="blank">
                            {cloudRequiredPrefix}
                        </Link>{' '}
                    </>
                ) : (
                    <>
                        For private repositories, append <code>?private_token=TOKEN</code> to the end of the URL.
                    </>
                )}
            </p>
            <div className="flex items-center gap-2">
                <LemonInput
                    value={pluginUrl}
                    onChange={setPluginUrl}
                    placeholder="https://github.com/PostHog/posthog-hello-world-plugin"
                    className="flex-1"
                />
                <LemonButton
                    disabledReason={disabledReason}
                    type="primary"
                    onClick={() => installPlugin(PluginInstallationType.Custom)}
                >
                    Fetch and install
                </LemonButton>
            </div>
        </>
    )
}

function InstallLocalApp(): JSX.Element {
    const { localPluginPath } = useValues(appsManagementLogic)
    const { setLocalPluginPath, installPlugin } = useActions(appsManagementLogic)

    return (
        <>
            <div>
                <h3 className="mt-3">Install from local path</h3>
                <p>To install a local app from this computer/server, give its full path below.</p>
                <div className="flex items-center gap-2">
                    <LemonInput
                        value={localPluginPath}
                        onChange={setLocalPluginPath}
                        placeholder="/var/posthog/apps/helloworldapp"
                        className="flex-1"
                    />
                    <LemonButton
                        disabledReason={!localPluginPath ? 'Please enter a path' : undefined}
                        type="primary"
                        onClick={() => installPlugin(PluginInstallationType.Local)}
                    >
                        Install
                    </LemonButton>
                </div>
            </div>
        </>
    )
}

function InstallSourceApp(): JSX.Element {
    const { sourcePluginName, sourcePluginKind } = useValues(appsManagementLogic)
    const { setSourcePluginName, installPlugin, setSourcePluginKind } = useActions(appsManagementLogic)

    const menuItems = Object.values(SourcePluginKind).map((kind) => ({
        label: kind,
        onClick: () => {
            setSourcePluginKind(kind)
        },
    }))

    return (
        <div>
            <h3 className="mt-3">Install by writing source code</h3>
            <p>
                To install a source app provide the name and start coding.
                <Link to="https://posthog.com/docs/apps" target="_blank">
                    {' '}
                    Read the documentation for more information!
                </Link>
            </p>
            <div className="flex items-center gap-2">
                <LemonInput
                    value={sourcePluginName}
                    onChange={setSourcePluginName}
                    placeholder="Hello World App"
                    className="flex-1"
                />
                <LemonMenu items={menuItems} placement="bottom-end">
                    <LemonButton size="small">{sourcePluginKind}</LemonButton>
                </LemonMenu>
                <LemonButton
                    disabledReason={!sourcePluginName ? 'Please enter a name' : undefined}
                    type="primary"
                    onClick={() => installPlugin(PluginInstallationType.Source)}
                >
                    Install
                </LemonButton>
            </div>
        </div>
    )
}
