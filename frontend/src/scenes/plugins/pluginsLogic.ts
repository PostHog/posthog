import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'
import type { pluginsLogicType } from './pluginsLogicType'
import api from 'lib/api'
import { PersonalAPIKeyType, PluginConfigType, PluginType } from '~/types'
import {
    PluginInstallationType,
    PluginRepositoryEntry,
    PluginTab,
    PluginTypeWithConfig,
    PluginUpdateStatusType,
} from './types'
import { userLogic } from 'scenes/userLogic'
import { getConfigSchemaArray, getConfigSchemaObject, getPluginConfigFormData } from 'scenes/plugins/utils'
import posthog from 'posthog-js'
import type { FormInstance } from 'antd/lib/form/hooks/useForm.d'
import { canGloballyManagePlugins, canInstallPlugins } from './access'
import { teamLogic } from '../teamLogic'
import { createDefaultPluginSource } from 'scenes/plugins/source/createDefaultPluginSource'
import { frontendAppsLogic } from 'scenes/apps/frontendAppsLogic'
import { urls } from 'scenes/urls'
import { lemonToast } from 'lib/lemon-ui/lemonToast'

export type PluginForm = FormInstance

export interface PluginSelectionType {
    name: string
    url?: string
}

const PAGINATION_DEFAULT_MAX_PAGES = 10

function capturePluginEvent(event: string, plugin: PluginType, type?: PluginInstallationType): void {
    posthog.capture(event, {
        plugin_name: plugin.name,
        plugin_url: plugin.url?.startsWith('file:') ? 'file://masked-local-path' : plugin.url,
        plugin_tag: plugin.tag,
        ...(type && { plugin_installation_type: type }),
    })
}

async function loadPaginatedResults(
    url: string | null,
    maxIterations: number = PAGINATION_DEFAULT_MAX_PAGES
): Promise<any[]> {
    let results: any[] = []
    for (let i = 0; i <= maxIterations; ++i) {
        if (!url) {
            break
        }

        const { results: partialResults, next } = await api.get(url)
        results = results.concat(partialResults)
        url = next
    }
    return results
}

export const pluginsLogic = kea<pluginsLogicType>([
    path(['scenes', 'plugins', 'pluginsLogic']),
    connect(frontendAppsLogic),
    actions({
        editPlugin: (id: number | null, pluginConfigChanges: Record<string, any> = {}) => ({ id, pluginConfigChanges }),
        savePluginConfig: (pluginConfigChanges: Record<string, any>) => ({ pluginConfigChanges }),
        installPlugin: (pluginUrl: string, pluginType: PluginInstallationType) => ({ pluginUrl, pluginType }),
        uninstallPlugin: (id: number) => ({ id }),
        setCustomPluginUrl: (customPluginUrl: string) => ({ customPluginUrl }),
        setLocalPluginUrl: (localPluginUrl: string) => ({ localPluginUrl }),
        setSourcePluginName: (sourcePluginName: string) => ({ sourcePluginName }),
        setPluginTab: (tab: PluginTab) => ({ tab }),
        setEditingSource: (editingSource: boolean) => ({ editingSource }),
        checkForUpdates: (checkAll: boolean, initialUpdateStatus: Record<string, PluginUpdateStatusType> = {}) => ({
            checkAll,
            initialUpdateStatus,
        }),
        checkedForUpdates: true,
        setUpdateStatus: (id: number, tag: string, latestTag: string) => ({ id, tag, latestTag }),
        setUpdateError: (id: number) => ({ id }),
        updatePlugin: (id: number) => ({ id }),
        pluginUpdated: (id: number) => ({ id }),
        patchPlugin: (id: number, pluginChanges: Partial<PluginType> = {}) => ({ id, pluginChanges }),
        generateApiKeysIfNeeded: (form: PluginForm) => ({ form }),
        setTemporaryOrder: (temporaryOrder: Record<number, number>, movedPluginId: number) => ({
            temporaryOrder,
            movedPluginId,
        }),
        savePluginOrders: (newOrders: Record<number, number>) => ({ newOrders }),
        cancelRearranging: true,
        showPluginLogs: (id: number) => ({ id }),
        hidePluginLogs: true,
        setSearchTerm: (term: string | null) => ({ term }),
        syncFrontendAppState: (id: number) => ({ id }),
        openAdvancedInstallModal: true,
        closeAdvancedInstallModal: true,
        openReorderModal: true,
        closeReorderModal: true,
    }),

    loaders(({ actions, values }) => ({
        plugins: [
            {} as Record<number, PluginType>,
            {
                loadPlugins: async () => {
                    const results: PluginType[] = await loadPaginatedResults('api/organizations/@current/plugins')
                    const plugins: Record<string, PluginType> = {}
                    for (const plugin of results) {
                        plugins[plugin.id] = plugin
                    }
                    return plugins
                },
                installPlugin: async ({ pluginUrl, pluginType }) => {
                    const url = pluginType === 'local' ? `file:${pluginUrl}` : pluginUrl
                    const response = await api.create(
                        'api/organizations/@current/plugins',
                        pluginType === 'source' ? { plugin_type: pluginType, name: url } : { url }
                    )
                    if (pluginType === 'source') {
                        await api.update(`api/organizations/@current/plugins/${response.id}/update_source`, {
                            'plugin.json': createDefaultPluginSource(url)['plugin.json'],
                        })
                        actions.loadPlugins()
                    }
                    capturePluginEvent(`plugin installed`, response, pluginType)

                    actions.closeAdvancedInstallModal()
                    return { ...values.plugins, [response.id]: response }
                },
                uninstallPlugin: async ({ id }) => {
                    await api.delete(`api/organizations/@current/plugins/${id}`)
                    capturePluginEvent(`plugin uninstalled`, values.plugins[id])
                    const { [id]: _discard, ...rest } = values.plugins
                    return rest
                },
                updatePlugin: async ({ id }) => {
                    const response = await api.create(`api/organizations/@current/plugins/${id}/upgrade`)
                    capturePluginEvent(`plugin updated`, response)
                    actions.pluginUpdated(id)
                    // Check if we need to update the config (e.g. new required field) and if so, open the drawer.
                    const schema = getConfigSchemaObject(response.config_schema)
                    const pluginConfig = Object.values(values.pluginConfigs).filter((c) => c.plugin === id)[0]
                    if (pluginConfig?.enabled) {
                        if (
                            Object.entries(schema).find(([key, { required }]) => required && !pluginConfig.config[key])
                        ) {
                            actions.editPlugin(id)
                        }
                    }

                    return { ...values.plugins, [id]: response }
                },
                patchPlugin: async ({ id, pluginChanges }) => {
                    const response = await api.update(`api/organizations/@current/plugins/${id}`, pluginChanges)
                    return { ...values.plugins, [id]: response }
                },
            },
        ],
        pluginConfigs: [
            {} as Record<string, PluginConfigType>,
            {
                loadPluginConfigs: async () => {
                    const pluginConfigs: Record<string, PluginConfigType> = {}
                    const results: PluginConfigType[] = await loadPaginatedResults('api/plugin_config')

                    for (const pluginConfig of results) {
                        pluginConfigs[pluginConfig.plugin] = { ...pluginConfig }
                    }

                    return pluginConfigs
                },
                savePluginConfig: async ({ pluginConfigChanges }) => {
                    const { pluginConfigs, editingPlugin } = values

                    if (!editingPlugin) {
                        return pluginConfigs
                    }

                    const formData = getPluginConfigFormData(editingPlugin, pluginConfigChanges)

                    if (!editingPlugin.pluginConfig?.enabled) {
                        formData.append('order', values.nextPluginOrder.toString())
                    }

                    let response: PluginConfigType
                    if (editingPlugin.pluginConfig.id) {
                        response = await api.update(`api/plugin_config/${editingPlugin.pluginConfig.id}`, formData)
                    } else {
                        formData.append('plugin', editingPlugin.id.toString())
                        response = await api.create(`api/plugin_config/`, formData)
                    }
                    capturePluginEvent(`plugin config updated`, editingPlugin)
                    if (editingPlugin.pluginConfig.enabled !== response.enabled) {
                        capturePluginEvent(`plugin ${response.enabled ? 'enabled' : 'disabled'}`, editingPlugin)
                    }
                    if ('id' in response) {
                        // Run the sync after we return from the loader, and save its data
                        window.setTimeout(() => response.id && actions.syncFrontendAppState(response.id), 0)
                    }
                    return { ...pluginConfigs, [response.plugin]: response }
                },
                toggleEnabled: async ({ id, enabled }) => {
                    const { pluginConfigs, plugins } = values
                    const pluginConfig = values.getPluginConfig(id)
                    if (pluginConfig) {
                        const plugin = plugins[pluginConfig.plugin]
                        if (plugin) {
                            capturePluginEvent(`plugin ${enabled ? 'enabled' : 'disabled'}`, plugin)
                        }
                    }
                    const response = await api.update(`api/plugin_config/${id}`, {
                        enabled,
                        order: values.nextPluginOrder,
                    })
                    return { ...pluginConfigs, [response.plugin]: response }
                },
                savePluginOrders: async ({ newOrders }) => {
                    const { pluginConfigs } = values
                    const response: PluginConfigType[] = await api.update(`api/plugin_config/rearrange`, {
                        orders: newOrders,
                    })
                    const newPluginConfigs: Record<string, PluginConfigType> = { ...pluginConfigs }
                    for (const pluginConfig of response) {
                        newPluginConfigs[pluginConfig.plugin] = pluginConfig
                    }
                    return newPluginConfigs
                },
            },
        ],
        repository: [
            {} as Record<string, PluginRepositoryEntry>,
            {
                loadRepository: async () => {
                    const results = await api.get('api/organizations/@current/plugins/repository')
                    const repository: Record<string, PluginRepositoryEntry> = {}
                    for (const plugin of results as PluginRepositoryEntry[]) {
                        if (plugin.url) {
                            repository[plugin.url.replace(/\/+$/, '')] = plugin
                        }
                    }
                    return repository
                },
            },
        ],
        unusedPlugins: [
            // used for know if plugin can be uninstalled
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
        plugins: {
            setUpdateStatus: (state, { id, tag, latestTag }) => ({
                ...state,
                [id]: { ...state[id], tag, latest_tag: latestTag },
            }),
        },
        installingPluginUrl: [
            null as string | null,
            {
                installPlugin: (_, { pluginUrl }) => pluginUrl,
                installPluginSuccess: () => null,
                installPluginFailure: () => null,
            },
        ],
        editingPluginId: [
            null as number | null,
            {
                editPlugin: (_, { id }) => id,
                savePluginConfigSuccess: () => null,
                uninstallPluginSuccess: () => null,
                installPluginSuccess: (_, { plugins }) => Object.values(plugins).pop()?.id || null,
            },
        ],
        editingPluginInitialChanges: [
            {} as Record<string, any>,
            {
                editPlugin: (_, { pluginConfigChanges }) => pluginConfigChanges,
                installPluginSuccess: () => ({ __enabled: true }),
            },
        ],
        editingSource: [
            false,
            {
                setEditingSource: (_, { editingSource }) => editingSource,
                editPlugin: () => false,
            },
        ],
        customPluginUrl: [
            '',
            {
                setCustomPluginUrl: (_, { customPluginUrl }) => customPluginUrl,
                installPluginSuccess: () => '',
            },
        ],
        localPluginUrl: [
            '',
            {
                setLocalPluginUrl: (_, { localPluginUrl }) => localPluginUrl,
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
        pluginError: [
            null as null | string,
            {
                setCustomPluginUrl: () => null,
                installPlugin: () => null,
                installPluginFailure: (_, { error }) => error || '',
            },
        ],
        pluginConfigs: {
            uninstallPluginSuccess: (pluginConfigs, { plugins }) => {
                const newPluginConfigs: Record<number, PluginConfigType> = {}
                Object.values(pluginConfigs).forEach((pluginConfig) => {
                    if (plugins[pluginConfig.plugin]) {
                        newPluginConfigs[pluginConfig.plugin] = pluginConfig
                    }
                })
                return newPluginConfigs
            },
        },
        pluginTab: [
            PluginTab.Apps as PluginTab,
            {
                setPluginTab: (_, { tab }) => tab,
            },
        ],
        updateStatus: [
            {} as Record<string, PluginUpdateStatusType>,
            {
                checkForUpdates: (_, { initialUpdateStatus }) => initialUpdateStatus,
                setUpdateStatus: (state, { id, tag, latestTag }) => ({
                    ...state,
                    [id]: { upToDate: tag === latestTag },
                }),
                setUpdateError: (state, { id }) => ({ ...state, [id]: { error: true } }),
                pluginUpdated: (state, { id }) => ({ ...state, [id]: { updated: true } }),
            },
        ],
        pluginsUpdating: [
            [] as number[],
            {
                updatePlugin: (plugins, { id }) => [...plugins, id],
                pluginUpdated: (plugins, { id }) => plugins.filter((pluginId) => pluginId !== id),
                setUpdateError: (plugins, { id }) => plugins.filter((pluginId) => pluginId !== id),
            },
        ],
        checkingForUpdates: [
            false,
            {
                checkForUpdates: () => true,
                checkedForUpdates: () => false,
            },
        ],
        temporaryOrder: [
            {} as Record<number, number>,
            {
                setTemporaryOrder: (_, { temporaryOrder }) => temporaryOrder,
                cancelRearranging: () => ({}),
                savePluginOrdersSuccess: () => ({}),
            },
        ],
        movedPlugins: [
            {} as Record<number, boolean>,
            {
                setTemporaryOrder: (state, { movedPluginId }) => ({ ...state, [movedPluginId]: true }),
                cancelRearranging: () => ({}),
                savePluginOrdersSuccess: () => ({}),
            },
        ],
        showingLogsPluginId: [
            null as number | null,
            {
                showPluginLogs: (_, { id }) => id,
                hidePluginLogs: () => null,
            },
        ],
        lastShownLogsPluginId: [
            null as number | null,
            {
                showPluginLogs: (_, { id }) => id,
            },
        ],
        searchTerm: [
            null as string | null,
            {
                setSearchTerm: (_, { term }) => term,
            },
        ],
        advancedInstallModalOpen: [
            false,
            {
                openAdvancedInstallModal: () => true,
                closeAdvancedInstallModal: () => false,
            },
        ],
        reorderModalOpen: [
            false,
            {
                openReorderModal: () => true,
                closeReorderModal: () => false,
            },
        ],
    }),

    selectors({
        getPluginConfig: [
            (s) => [s.pluginConfigs],
            (pluginConfigs): ((id: number) => PluginConfigType | undefined) =>
                (id: number) =>
                    Object.values(pluginConfigs).find(({ id: _id }) => id === _id),
        ],
        installedPlugins: [
            (s) => [s.plugins, s.pluginConfigs, s.updateStatus],
            (plugins, pluginConfigs, updateStatus): PluginTypeWithConfig[] => {
                const { currentTeam } = teamLogic.values
                if (!currentTeam) {
                    lemonToast.error("Can't list installed plugins with no user or team!")
                    return []
                }

                const pluginValues = Object.values(plugins)

                return pluginValues
                    .map((plugin, index) => {
                        let pluginConfig: PluginConfigType = { ...pluginConfigs[plugin.id] }
                        if (!pluginConfigs[plugin.id]) {
                            const config: Record<string, any> = {}
                            Object.entries(getConfigSchemaObject(plugin.config_schema)).forEach(
                                ([key, { default: def }]) => {
                                    config[key] = def
                                }
                            )

                            pluginConfig = {
                                id: undefined,
                                team_id: currentTeam.id,
                                plugin: plugin.id,
                                enabled: false,
                                config: config,
                                order: pluginValues.length + index,
                            }
                        }
                        return { ...plugin, pluginConfig, updateStatus: updateStatus[plugin.id] }
                    })
                    .sort((p1, p2) => p1.name.toUpperCase().localeCompare(p2.name.toUpperCase()))
            },
        ],
        enabledPlugins: [
            (s) => [s.installedPlugins, s.movedPlugins, s.temporaryOrder],
            (installedPlugins, movedPlugins, temporaryOrder) =>
                [...installedPlugins.filter(({ pluginConfig }) => pluginConfig?.enabled)]
                    .map((plugin) => ({
                        ...plugin,
                        pluginConfig: {
                            ...plugin.pluginConfig,
                            order: temporaryOrder[plugin.id] ?? plugin.pluginConfig.order,
                        },
                    }))
                    .sort((a, b) => a.pluginConfig.order - b.pluginConfig.order)
                    .map((plugin, index) => ({
                        ...plugin,
                        pluginConfig: { ...plugin.pluginConfig, order: index + 1 },
                        hasMoved: movedPlugins[plugin.id],
                    })) as PluginTypeWithConfig[],
        ],
        nextPluginOrder: [
            (s) => [s.enabledPlugins],
            (enabledPlugins) =>
                enabledPlugins.reduce((maxOrder, plugin) => Math.max(plugin.pluginConfig?.order ?? 0, maxOrder), 0) + 1,
        ],
        disabledPlugins: [
            (s) => [s.installedPlugins],
            (installedPlugins) =>
                installedPlugins
                    .filter(({ pluginConfig }) => !pluginConfig?.enabled)
                    .sort((a, b) => Number(a.is_global) - Number(b.is_global)),
        ],
        pluginsNeedingUpdates: [
            (s) => [s.installedPlugins, userLogic.selectors.user],
            (installedPlugins, user) => {
                // Disable this for orgs who can't install plugins
                if (!canInstallPlugins(user?.organization)) {
                    return []
                }
                // Show either plugins that need to be updated or that were just updated, and only the current org's
                return installedPlugins.filter(
                    ({ plugin_type, tag, latest_tag, updateStatus, organization_id }) =>
                        organization_id === user?.organization?.id &&
                        plugin_type !== PluginInstallationType.Source &&
                        ((latest_tag && tag !== latest_tag) ||
                            (updateStatus && !updateStatus.error && (updateStatus.updated || !updateStatus.upToDate)))
                )
            },
        ],
        installedPluginUrls: [
            (s) => [s.installedPlugins, userLogic.selectors.user],
            (installedPlugins, user) => {
                const names: Record<string, boolean> = {}
                installedPlugins.forEach((plugin) => {
                    if (plugin.url && plugin.organization_id === user?.organization?.id) {
                        names[plugin.url.replace(/\/+$/, '')] = true
                    }
                })
                return names
            },
        ],
        updatablePlugins: [
            (s) => [s.installedPlugins, userLogic.selectors.user],
            (installedPlugins, user) =>
                installedPlugins.filter(
                    (plugin) =>
                        plugin.plugin_type !== PluginInstallationType.Source &&
                        !plugin.url?.startsWith('file:') &&
                        user?.organization?.id === plugin.organization_id
                ),
        ],
        hasUpdatablePlugins: [(s) => [s.updatablePlugins], (updatablePlugins) => updatablePlugins.length > 0],
        uninstalledPlugins: [
            (s) => [s.installedPluginUrls, s.repository],
            (installedPluginUrls, repository) => {
                return Object.keys(repository)
                    .filter((url) => !installedPluginUrls[url.replace(/\/+$/, '')])
                    .map((url) => repository[url.replace(/\/+$/, '')])
                    .sort((p1, p2) => p1.name.toUpperCase().localeCompare(p2.name.toUpperCase()))
            },
        ],
        editingPlugin: [
            (s) => [s.editingPluginId, s.installedPlugins],
            (editingPluginId, installedPlugins) =>
                editingPluginId ? installedPlugins.find((plugin) => plugin.id === editingPluginId) : null,
        ],
        loading: [
            (s) => [s.pluginsLoading, s.repositoryLoading, s.pluginConfigsLoading],
            (pluginsLoading, repositoryLoading, pluginConfigsLoading) =>
                pluginsLoading || repositoryLoading || pluginConfigsLoading,
        ],
        showingLogsPlugin: [
            (s) => [s.showingLogsPluginId, s.installedPlugins],
            (showingLogsPluginId, installedPlugins) =>
                showingLogsPluginId ? installedPlugins.find((plugin) => plugin.id === showingLogsPluginId) : null,
        ],
        lastShownLogsPlugin: [
            (s) => [s.lastShownLogsPluginId, s.installedPlugins],
            (lastShownLogsPluginId, installedPlugins) =>
                lastShownLogsPluginId ? installedPlugins.find((plugin) => plugin.id === lastShownLogsPluginId) : null,
        ],
        filteredUninstalledPlugins: [
            (s) => [s.searchTerm, s.uninstalledPlugins],
            (searchTerm, uninstalledPlugins) =>
                searchTerm
                    ? uninstalledPlugins.filter((plugin) =>
                          plugin.name.toLowerCase().includes(searchTerm.toLowerCase())
                      )
                    : uninstalledPlugins,
        ],
        filteredDisabledPlugins: [
            (s) => [s.searchTerm, s.disabledPlugins],
            (searchTerm, disabledPlugins) =>
                searchTerm
                    ? disabledPlugins.filter((plugin) => plugin.name.toLowerCase().includes(searchTerm.toLowerCase()))
                    : disabledPlugins,
        ],
        filteredEnabledPlugins: [
            (s) => [s.searchTerm, s.enabledPlugins],
            (searchTerm, enabledPlugins) =>
                searchTerm
                    ? enabledPlugins.filter((plugin) => plugin.name.toLowerCase().includes(searchTerm.toLowerCase()))
                    : enabledPlugins,
        ],
        filteredPluginsNeedingUpdates: [
            (s) => [s.searchTerm, s.pluginsNeedingUpdates],
            (searchTerm, pluginsNeedingUpdates) =>
                searchTerm
                    ? pluginsNeedingUpdates.filter((plugin) =>
                          plugin.name.toLowerCase().includes(searchTerm.toLowerCase())
                      )
                    : pluginsNeedingUpdates,
        ],
        sortableEnabledPlugins: [
            (s) => [s.filteredEnabledPlugins],
            (filteredEnabledPlugins) => {
                return filteredEnabledPlugins.filter(
                    (plugin) =>
                        !plugin.capabilities ||
                        (plugin.capabilities.methods &&
                            (plugin.capabilities.methods.includes('processEvent') ||
                                plugin.capabilities.methods.includes('processEventBatch')))
                )
            },
        ],
        unsortableEnabledPlugins: [
            (s) => [s.filteredEnabledPlugins, s.sortableEnabledPlugins],
            (filteredEnabledPlugins, sortableEnabledPlugins) => {
                return filteredEnabledPlugins.filter(
                    (enabledPlugin) => !sortableEnabledPlugins.map((plugin) => plugin.name).includes(enabledPlugin.name)
                )
            },
        ],
        pluginUrlToMaintainer: [
            (s) => [s.repository],
            (repository) => {
                const pluginNameToMaintainerMap: Record<string, string> = {}
                for (const plugin of Object.values(repository)) {
                    pluginNameToMaintainerMap[plugin.url] = plugin.maintainer || ''
                }
                return pluginNameToMaintainerMap
            },
        ],
        allPossiblePlugins: [
            (s) => [s.repository, s.plugins],
            (repository, plugins) => {
                const allPossiblePlugins: PluginSelectionType[] = []
                for (const plugin of Object.values(plugins)) {
                    allPossiblePlugins.push({ name: plugin.name, url: plugin.url })
                }

                const installedUrls = new Set(Object.values(plugins).map((plugin) => plugin.url))

                for (const plugin of Object.values(repository)) {
                    if (!installedUrls.has(plugin.url)) {
                        allPossiblePlugins.push({ name: plugin.name, url: plugin.url })
                    }
                }
                return allPossiblePlugins
            },
        ],
        showAppMetricsForPlugin: [
            () => [],
            () => (plugin: Partial<PluginTypeWithConfig> | undefined) => {
                return plugin?.capabilities?.methods?.length || plugin?.capabilities?.scheduled_tasks?.length
            },
        ],
    }),

    listeners(({ actions, values }) => ({
        // Load or unload an app, as directed by its enabled state in pluginsLogic
        syncFrontendAppState: ({ id }) => {
            const pluginConfig = values.getPluginConfig(id)
            if (pluginConfig) {
                frontendAppsLogic.actions.unloadFrontendApp(id)
                if (pluginConfig.enabled) {
                    frontendAppsLogic.actions.loadFrontendApp(id, pluginConfig.plugin, true)
                }
            }
        },
        checkForUpdates: async ({ checkAll }, breakpoint) => {
            breakpoint()
            const { updatablePlugins } = values
            const pluginsToCheck = checkAll ? updatablePlugins : updatablePlugins.filter((plugin) => !plugin.latest_tag)

            for (const plugin of pluginsToCheck) {
                try {
                    const updates = await api.get(`api/organizations/@current/plugins/${plugin.id}/check_for_updates`)
                    actions.setUpdateStatus(plugin.id, updates.plugin.tag, updates.plugin.latest_tag)
                } catch (e) {
                    actions.setUpdateError(plugin.id)
                }
                breakpoint()
            }

            actions.checkedForUpdates()
        },
        loadPluginsSuccess() {
            const initialUpdateStatus: Record<string, PluginUpdateStatusType> = {}
            for (const [id, plugin] of Object.entries(values.plugins)) {
                if (plugin.latest_tag) {
                    initialUpdateStatus[id] = { upToDate: plugin.tag === plugin.latest_tag }
                }
            }
            if (canInstallPlugins(userLogic.values.user?.organization)) {
                actions.checkForUpdates(false, initialUpdateStatus)
            }
        },
        generateApiKeysIfNeeded: async ({ form }, breakpoint) => {
            const { editingPlugin } = values
            if (!editingPlugin) {
                return
            }

            const pluginConfig = editingPlugin.pluginConfig.config
            const configSchema = getConfigSchemaArray(editingPlugin?.config_schema || [])

            const posthogApiKeySchema = configSchema.find(({ key }) => key === 'posthogApiKey')
            if (posthogApiKeySchema && !pluginConfig?.posthogApiKey) {
                try {
                    const { value: posthogApiKey }: PersonalAPIKeyType = await api.create('api/personal_api_keys/', {
                        label: `Plugin: ${editingPlugin.name}`,
                    })
                    breakpoint()
                    form.setFieldsValue({ posthogApiKey })
                } catch (e) {
                    console.error(e)
                }
            }

            const posthogHostSchema = configSchema.find(({ key }) => key === 'posthogHost')
            if (
                posthogHostSchema &&
                (!pluginConfig?.posthogHost || pluginConfig.posthogHost === 'https://app.posthog.com')
            ) {
                form.setFieldsValue({ posthogHost: window.location.origin })
            }
        },

        savePluginOrdersSuccess: () => {
            actions.closeReorderModal()
        },
    })),
    actionToUrl(({ values }) => {
        function getUrl(): string {
            return values.showingLogsPluginId
                ? urls.projectAppLogs(values.showingLogsPluginId)
                : values.editingPluginId
                ? values.editingSource
                    ? urls.projectAppSource(values.editingPluginId)
                    : urls.projectApp(values.editingPluginId)
                : urls.projectApps()
        }
        return {
            setPluginTab: () => {
                if (router.values.location.pathname !== urls.projectApps()) {
                    return // This logic can be mounted when on outside of the Apps page too - don't change the URL then
                }
                const searchParams = {
                    ...router.values.searchParams,
                }

                let replace = false // set a page in history
                if (!searchParams['tab'] && values.pluginTab === PluginTab.Apps) {
                    // we are on the Apps page, and have clicked the Apps tab, don't set history
                    replace = true
                }
                searchParams['tab'] = values.pluginTab

                return [router.values.location.pathname, searchParams, router.values.hashParams, { replace }]
            },
            editPlugin: () => [getUrl()],
            setEditingSource: () => [getUrl()],
            hidePluginLogs: () => [getUrl()],
            showPluginLogs: () => [getUrl()],
        }
    }),
    urlToAction(({ actions, values }) => {
        function runActions(editingId: number | null, editingSource: boolean, logsId: number | null): void {
            if (values.editingPluginId !== editingId) {
                actions.editPlugin(editingId)
            }
            if (values.showingLogsPluginId !== logsId) {
                if (logsId) {
                    actions.showPluginLogs(logsId)
                } else {
                    actions.hidePluginLogs()
                }
            }
            if (editingSource !== values.editingSource) {
                actions.setEditingSource(editingSource)
            }
        }
        return {
            [urls.projectApps()]: (_, { tab, name }) => {
                if (tab) {
                    actions.setPluginTab(tab as PluginTab)
                }
                if (name && values.pluginTab === PluginTab.Apps) {
                    actions.setSearchTerm(name)
                }
                runActions(null, false, null)
            },
            [urls.projectApp(':id')]: ({ id }) => {
                runActions(id ? parseInt(id) : null, false, null)
            },
            [urls.projectAppSource(':id')]: ({ id }) => {
                runActions(id ? parseInt(id) : null, true, null)
            },
            [urls.projectAppLogs(':id')]: ({ id }) => {
                runActions(null, false, id ? parseInt(id) : null)
            },
        }
    }),

    afterMount(({ actions }) => {
        actions.loadPlugins()
        actions.loadPluginConfigs()
        if (canGloballyManagePlugins(userLogic.values.user?.organization)) {
            actions.loadRepository()
            actions.loadUnusedPlugins()
        }
    }),
])
