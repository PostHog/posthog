import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import posthog from 'posthog-js'
import { userLogic } from 'scenes/userLogic'

import { PluginInstallationType, PluginType } from '~/types'

import { canInstallPlugins } from './access'
import type { appsManagementLogicType } from './appsManagementLogicType'
import { pipelineAccessLogic } from './pipelineAccessLogic'
import { getInitialCode, SourcePluginKind } from './sourceAppInitialCode'
import { GLOBAL_PLUGINS, loadPluginsFromUrl } from './utils'

function capturePluginEvent(event: string, plugin: PluginType, type: PluginInstallationType): void {
    posthog.capture(event, {
        plugin_name: plugin.name,
        plugin_url: plugin.url?.startsWith('file:') ? 'file://masked-local-path' : plugin.url,
        plugin_tag: plugin.tag,
        plugin_installation_type: type,
    })
}
export interface PluginUpdateStatusType {
    latest_tag: string
    upToDate: boolean
    updated: boolean
    error: string | null
}

export const appsManagementLogic = kea<appsManagementLogicType>([
    path(['scenes', 'pipeline', 'appsManagementLogic']),
    connect({
        values: [userLogic, ['user'], pipelineAccessLogic, ['canGloballyManagePlugins']],
    }),
    actions({
        setPluginUrl: (pluginUrl: string) => ({ pluginUrl }),
        setLocalPluginPath: (localPluginPath: string) => ({ localPluginPath }),
        setSourcePluginName: (sourcePluginName: string) => ({ sourcePluginName }),
        setSourcePluginKind: (sourcePluginKind: SourcePluginKind) => ({ sourcePluginKind }),
        uninstallPlugin: (id: number) => ({ id }),
        installPlugin: (pluginType: PluginInstallationType, url?: string) => ({ pluginType, url }),
        installPluginFromUrl: (url: string) => ({ url }),
        installSourcePlugin: (name: string) => ({ name }),
        installLocalPlugin: (path: string) => ({ path }),
        patchPlugin: (id: number, pluginChanges: Partial<PluginType> = {}) => ({ id, pluginChanges }),
        updatePlugin: (id: number) => ({ id }),
        checkForUpdates: true,
        checkedForUpdates: true,
        setPluginLatestTag: (id: number, latestTag: string) => ({ id, latestTag }),
    }),
    loaders(({ values }) => ({
        plugins: [
            {} as Record<number, PluginType>,
            {
                loadPlugins: async () => {
                    return loadPluginsFromUrl('api/organizations/@current/plugins')
                },
                installPlugin: async ({ pluginType, url }) => {
                    if (!values.canInstallPlugins) {
                        lemonToast.error("You don't have permission to install apps.")
                        return values.plugins
                    }
                    const payload: any = { plugin_type: pluginType }
                    if (url || pluginType === PluginInstallationType.Repository) {
                        payload.url = url
                    } else if (pluginType === PluginInstallationType.Custom) {
                        payload.url = values.pluginUrl
                    } else if (pluginType === PluginInstallationType.Local) {
                        payload.url = `file:${values.localPluginPath}`
                    } else if (pluginType === PluginInstallationType.Source) {
                        payload.name = values.sourcePluginName
                    } else {
                        lemonToast.error('Unsupported installation type.')
                        return values.plugins
                    }
                    const response: PluginType = await api.create('api/organizations/@current/plugins', payload)
                    if (pluginType === PluginInstallationType.Source) {
                        await api.update(
                            `api/organizations/@current/plugins/${response.id}/update_source`,
                            getInitialCode(values.sourcePluginName, values.sourcePluginKind)
                        )
                    }
                    capturePluginEvent(`plugin installed`, response, pluginType)
                    return { ...values.plugins, [response.id]: response }
                },
                uninstallPlugin: async ({ id }) => {
                    if (!values.canGloballyManagePlugins) {
                        lemonToast.error("You don't have permission to manage apps.")
                    }
                    await api.delete(`api/organizations/@current/plugins/${id}`)
                    capturePluginEvent(`plugin uninstalled`, values.plugins[id], values.plugins[id].plugin_type)
                    const { [id]: _discard, ...rest } = values.plugins
                    return rest
                },
                patchPlugin: async ({ id, pluginChanges }) => {
                    if (!values.canGloballyManagePlugins) {
                        lemonToast.error("You don't have permission to update apps.")
                    }
                    const response = await api.update(`api/organizations/@current/plugins/${id}`, pluginChanges)
                    return { ...values.plugins, [id]: response }
                },
                setPluginLatestTag: async ({ id, latestTag }) => {
                    return { ...values.plugins, [id]: { ...values.plugins[id], latest_tag: latestTag } }
                },
                updatePlugin: async ({ id }) => {
                    if (!values.canGloballyManagePlugins) {
                        lemonToast.error("You don't have permission to update apps.")
                    }
                    // TODO: the update failed
                    const response = await api.create(`api/organizations/@current/plugins/${id}/upgrade`)
                    capturePluginEvent(`plugin updated`, values.plugins[id], values.plugins[id].plugin_type)
                    lemonToast.success(`Plugin ${response.name} updated!`)
                    return { ...values.plugins, [id]: response }
                },
            },
        ],
        unusedPlugins: [
            // used to know if plugin can be uninstalled
            [] as number[],
            {
                loadUnusedPlugins: async () => {
                    const results = await api.get('api/organizations/@current/plugins/unused')
                    return results
                },
            },
        ],
    })),
    reducers({
        installingPluginUrl: [
            null as string | null,
            {
                installPlugin: (_, { url }) => url || null,
                installPluginSuccess: () => null,
                installPluginFailure: () => null,
            },
        ],
        pluginUrl: [
            '',
            {
                setPluginUrl: (_, { pluginUrl }) => pluginUrl,
                installPluginSuccess: () => '',
            },
        ],
        localPluginPath: [
            '',
            {
                setLocalPluginPath: (_, { localPluginPath }) => localPluginPath,
                installPluginSuccess: () => '',
            },
        ],
        sourcePluginName: [
            '',
            {
                setSourcePluginName: (_, { sourcePluginName }) => sourcePluginName,
                installPluginSuccess: () => '',
            },
        ],
        sourcePluginKind: [
            SourcePluginKind.FilterEvent as SourcePluginKind,
            {
                setSourcePluginKind: (_, { sourcePluginKind }) => sourcePluginKind,
                installPluginSuccess: () => SourcePluginKind.FilterEvent,
            },
        ],
        checkingForUpdates: [
            false,
            {
                checkForUpdates: () => true,
                checkedForUpdates: () => false,
            },
        ],
    }),
    selectors({
        canInstallPlugins: [(s) => [s.user], (user) => canInstallPlugins(user?.organization)],
        inlinePlugins: [
            (s) => [s.plugins],
            (plugins) =>
                Object.values(plugins).filter((plugin) => plugin.plugin_type === PluginInstallationType.Inline),
        ],
        appPlugins: [
            (s) => [s.plugins],
            (plugins) =>
                Object.values(plugins).filter((plugin) => plugin.plugin_type !== PluginInstallationType.Inline),
        ],
        globalPlugins: [
            (s) => [s.appPlugins],
            (plugins) => Object.values(plugins).filter((plugin) => plugin.is_global),
        ],
        localPlugins: [
            (s) => [s.appPlugins],
            (plugins) => Object.values(plugins).filter((plugin) => !plugin.is_global),
        ],
        missingGlobalPlugins: [
            (s) => [s.appPlugins],
            (plugins) => {
                const existingUrls = new Set(Object.values(plugins).map((p) => p.url))
                return Array.from(GLOBAL_PLUGINS).filter((url) => !existingUrls.has(url))
            },
        ],
        shouldBeGlobalPlugins: [
            (s) => [s.appPlugins],
            (plugins) => {
                return Object.values(plugins).filter(
                    (plugin) => plugin.url && GLOBAL_PLUGINS.has(plugin.url) && !plugin.is_global
                )
            },
        ],
        shouldNotBeGlobalPlugins: [
            (s) => [s.appPlugins],
            (plugins) => {
                return Object.values(plugins).filter(
                    (plugin) => !(plugin.url && GLOBAL_PLUGINS.has(plugin.url)) && plugin.is_global
                )
            },
        ],
        updatablePlugins: [
            (s) => [s.appPlugins],
            (plugins) =>
                Object.values(plugins).filter(
                    (plugin) => plugin.plugin_type !== PluginInstallationType.Source && !plugin.url?.startsWith('file:')
                ),
        ],
        pluginsNeedingUpdates: [
            (s) => [s.updatablePlugins],
            (plugins) => {
                return plugins.filter((plugin) => plugin.latest_tag && plugin.tag !== plugin.latest_tag)
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        checkForUpdates: async () => {
            await Promise.all(
                values.updatablePlugins.map(async (plugin) => {
                    try {
                        const updates = await api.get(
                            `api/organizations/@current/plugins/${plugin.id}/check_for_updates`
                        )
                        actions.setPluginLatestTag(plugin.id, updates.plugin.latest_tag)
                    } catch (e) {
                        lemonToast.error(`Error checking for updates for ${plugin.name}: ${JSON.stringify(e)}`)
                    }
                })
            )

            actions.checkedForUpdates()
        },
    })),
    afterMount(({ actions }) => {
        actions.loadPlugins()
        actions.loadUnusedPlugins()
        actions.checkForUpdates()
    }),
])
