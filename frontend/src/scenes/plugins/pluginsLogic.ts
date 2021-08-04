import { kea } from 'kea'
import { pluginsLogicType } from './pluginsLogicType'
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
import { FormInstance } from 'antd/lib/form'
import { canGloballyManagePlugins, canInstallPlugins } from './access'

type PluginForm = FormInstance

export enum PluginSection {
    Upgrade = 'upgrade',
    Installed = 'installed',
    Enabled = 'enabled',
    Disabled = 'disabled',
}

function capturePluginEvent(event: string, plugin: PluginType, type?: PluginInstallationType): void {
    posthog.capture(event, {
        plugin_name: plugin.name,
        plugin_url: plugin.url?.startsWith('file:') ? 'file://masked-local-path' : plugin.url,
        plugin_tag: plugin.tag,
        ...(type && { plugin_installation_type: type }),
    })
}

export const pluginsLogic = kea<pluginsLogicType<PluginForm, PluginSection>>({
    actions: {
        editPlugin: (id: number | null, pluginConfigChanges: Record<string, any> = {}) => ({ id, pluginConfigChanges }),
        savePluginConfig: (pluginConfigChanges: Record<string, any>) => ({ pluginConfigChanges }),
        installPlugin: (pluginUrl: string, pluginType: PluginInstallationType) => ({ pluginUrl, pluginType }),
        uninstallPlugin: (name: string) => ({ name }),
        setCustomPluginUrl: (customPluginUrl: string) => ({ customPluginUrl }),
        setLocalPluginUrl: (localPluginUrl: string) => ({ localPluginUrl }),
        setSourcePluginName: (sourcePluginName: string) => ({ sourcePluginName }),
        setPluginTab: (tab: PluginTab) => ({ tab }),
        setEditingSource: (editingSource: boolean) => ({ editingSource }),
        resetPluginConfigError: (id: number) => ({ id }),
        editPluginSource: (values: { id: number; name: string; source: string; configSchema: Record<string, any> }) =>
            values,
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
        rearrange: true,
        setTemporaryOrder: (temporaryOrder: Record<number, number>, movedPluginId: number) => ({
            temporaryOrder,
            movedPluginId,
        }),
        makePluginOrderSaveable: true,
        savePluginOrders: (newOrders: Record<number, number>) => ({ newOrders }),
        cancelRearranging: true,
        showPluginLogs: (id: number) => ({ id }),
        hidePluginLogs: true,
        showPluginMetrics: (id: number) => ({ id }),
        hidePluginMetrics: true,
        processSearchInput: (term: string) => ({ term }),
        setSearchTerm: (term: string | null) => ({ term }),
        setPluginConfigPollTimeout: (timeout: number | null) => ({ timeout }),
        toggleSectionOpen: (section: PluginSection) => ({ section }),
    },

    loaders: ({ actions, values }) => ({
        plugins: [
            {} as Record<number, PluginType>,
            {
                loadPlugins: async () => {
                    const { results } = await api.get('api/organizations/@current/plugins')
                    const plugins: Record<string, PluginType> = {}
                    for (const plugin of results as PluginType[]) {
                        plugins[plugin.id] = plugin
                    }
                    return plugins
                },
                installPlugin: async ({ pluginUrl, pluginType }) => {
                    const url = pluginType === 'local' ? `file:${pluginUrl}` : pluginUrl
                    const response = await api.create(
                        'api/organizations/@current/plugins',
                        pluginType === 'source' ? { plugin_type: pluginType, name: url, source: '' } : { url }
                    )
                    capturePluginEvent(`plugin installed`, response, pluginType)
                    return { ...values.plugins, [response.id]: response }
                },
                uninstallPlugin: async () => {
                    const { plugins, editingPlugin } = values
                    if (!editingPlugin) {
                        return plugins
                    }
                    await api.delete(`api/organizations/@current/plugins/${editingPlugin.id}`)
                    capturePluginEvent(`plugin uninstalled`, editingPlugin)
                    const { [editingPlugin.id]: _discard, ...rest } = plugins // eslint-disable-line
                    return rest
                },
                editPluginSource: async ({ id, name, source, configSchema }) => {
                    const { plugins } = values
                    const response = await api.update(`api/organizations/@current/plugins/${id}`, {
                        name,
                        source,
                        config_schema: configSchema,
                    })
                    capturePluginEvent(`plugin source edited`, response)
                    return { ...plugins, [id]: response }
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
                    if (!!values.pluginConfigPollTimeout) {
                        clearTimeout(values.pluginConfigPollTimeout)
                    }
                    // poll for plugin configs every 5s
                    // needed for "live" erroring without web sockets
                    actions.setPluginConfigPollTimeout(
                        window.setTimeout(() => {
                            actions.loadPluginConfigs()
                        }, 5000)
                    )

                    const pluginConfigs: Record<string, PluginConfigType> = {}
                    const { results } = await api.get('api/plugin_config')

                    for (const pluginConfig of results as PluginConfigType[]) {
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

                    let response
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

                    return { ...pluginConfigs, [response.plugin]: response }
                },
                toggleEnabled: async ({ id, enabled }) => {
                    const { pluginConfigs, plugins } = values
                    // pluginConfigs are indexed by plugin id, must look up the right config manually
                    const pluginConfig = Object.values(pluginConfigs).find((config) => config.id === id)
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
                resetPluginConfigError: async ({ id }) => {
                    const { pluginConfigs } = values
                    const response = await api.update(`api/plugin_config/${id}`, {
                        error: null,
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
    }),

    reducers: {
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
                editPluginSourceSuccess: () => false,
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
            PluginTab.Installed as PluginTab,
            {
                setPluginTab: (_, { tab }) => tab,
                installPluginSuccess: () => PluginTab.Installed,
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
        pluginOrderSaveable: [
            false,
            {
                makePluginOrderSaveable: () => true,
                cancelRearranging: () => false,
                savePluginOrdersSuccess: () => false,
            },
        ],
        rearranging: [
            false,
            {
                rearrange: () => true,
                cancelRearranging: () => false,
                savePluginOrdersSuccess: () => false,
            },
        ],
        temporaryOrder: [
            {} as Record<number, number>,
            {
                rearrange: () => ({}),
                setTemporaryOrder: (_, { temporaryOrder }) => temporaryOrder,
                cancelRearranging: () => ({}),
                savePluginOrdersSuccess: () => ({}),
            },
        ],
        movedPlugins: [
            {} as Record<number, boolean>,
            {
                rearrange: () => ({}),
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
        showingMetricsPluginId: [
            null as number | null,
            {
                showPluginMetrics: (_, { id }) => id,
                hidePluginMetrics: () => null,
            },
        ],
        searchTerm: [
            null as string | null,
            {
                setSearchTerm: (_, { term }) => term,
            },
        ],
        pluginConfigPollTimeout: [
            null as NodeJS.Timeout | null,
            {
                setPluginConfigPollTimeout: (_, { timeout }) => timeout,
            },
        ],
        sectionsOpen: [
            [PluginSection.Enabled, PluginSection.Disabled] as PluginSection[],
            {
                toggleSectionOpen: (currentOpenSections, { section }) => {
                    if (currentOpenSections.includes(section)) {
                        return currentOpenSections.filter((s) => section !== s)
                    }
                    return [...currentOpenSections, section]
                },
            },
        ],
    },

    selectors: {
        installedPlugins: [
            (s) => [s.plugins, s.pluginConfigs, s.updateStatus],
            (plugins, pluginConfigs, updateStatus): PluginTypeWithConfig[] => {
                const pluginValues = Object.values(plugins)
                return pluginValues
                    .map((plugin, index) => {
                        let pluginConfig: PluginConfigType = { ...pluginConfigs[plugin.id] }
                        if (!pluginConfig) {
                            const config: Record<string, any> = {}
                            Object.entries(getConfigSchemaObject(plugin.config_schema)).forEach(
                                ([key, { default: def }]) => {
                                    config[key] = def
                                }
                            )
                            const team = userLogic.values.user?.team
                            if (!team) {
                                throw new Error("Can't list installed plugins with no user or team!")
                            }
                            pluginConfig = {
                                id: undefined,
                                team_id: team.id,
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
        showingMetricsPlugin: [
            (s) => [s.showingMetricsPluginId, s.installedPlugins],
            (showingMetricsPluginId, installedPlugins) =>
                showingMetricsPluginId ? installedPlugins.find((plugin) => plugin.id === showingMetricsPluginId) : null,
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
    },

    listeners: ({ actions, values }) => ({
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
                if (
                    Object.keys(values.plugins).length === 0 &&
                    canGloballyManagePlugins(userLogic.values.user?.organization)
                ) {
                    actions.setPluginTab(PluginTab.Repository)
                }
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
    }),
    events: ({ actions, values }) => ({
        afterMount: () => {
            actions.loadPlugins()
            actions.loadPluginConfigs()
            if (canGloballyManagePlugins(userLogic.values.user?.organization)) {
                actions.loadRepository()
            }
        },
        beforeUnmount: () => {
            if (!!values.pluginConfigPollTimeout) {
                clearTimeout(values.pluginConfigPollTimeout)
            }
        },
    }),
})
