import { kea } from 'kea'
import { pluginsLogicType } from 'types/scenes/plugins/pluginsLogicType'
import api from 'lib/api'
import { PluginConfigType, PluginType } from '~/types'
import { PluginInstallationType, PluginRepositoryEntry, PluginTab, PluginTypeWithConfig } from './types'
import { userLogic } from 'scenes/userLogic'
import { getConfigSchemaObject, getPluginConfigFormData } from 'scenes/plugins/utils'
import posthog from 'posthog-js'

function capturePluginEvent(event: string, plugin: PluginType, type?: PluginInstallationType): void {
    posthog.capture(event, {
        plugin_name: plugin.name,
        plugin_url: plugin.url?.startsWith('file:') ? 'file://masked-local-path' : plugin.url,
        plugin_tag: plugin.tag,
        ...(type && { plugin_installation_type: type }),
    })
}

export const pluginsLogic = kea<
    pluginsLogicType<
        PluginType,
        PluginConfigType,
        PluginRepositoryEntry,
        PluginTypeWithConfig,
        PluginInstallationType,
        PluginTab
    >
>({
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
    },

    loaders: ({ values }) => ({
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
            },
        ],
        pluginConfigs: [
            {} as Record<string, PluginConfigType>,
            {
                loadPluginConfigs: async () => {
                    const pluginConfigs: Record<string, PluginConfigType> = {}

                    const [{ results }, globalResults] = await Promise.all([
                        api.get('api/plugin_config'),
                        api.get('api/plugin_config/global_plugins/'),
                    ])

                    for (const pluginConfig of results as PluginConfigType[]) {
                        pluginConfigs[pluginConfig.plugin] = { ...pluginConfig, global: false }
                    }
                    for (const pluginConfig of globalResults as PluginConfigType[]) {
                        pluginConfigs[pluginConfig.plugin] = { ...pluginConfig, global: true }
                    }

                    return pluginConfigs
                },
                savePluginConfig: async ({ pluginConfigChanges }) => {
                    const { pluginConfigs, editingPlugin } = values

                    if (!editingPlugin) {
                        return pluginConfigs
                    }

                    const formData = getPluginConfigFormData(editingPlugin, pluginConfigChanges)

                    let response
                    if (editingPlugin.pluginConfig.id) {
                        response = await api.update(`api/plugin_config/${editingPlugin.pluginConfig.id}`, formData)
                    } else {
                        formData.append('plugin', editingPlugin.id.toString())
                        formData.append('order', '0')
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
    },

    selectors: {
        installedPlugins: [
            (s) => [s.plugins, s.pluginConfigs],
            (plugins, pluginConfigs): PluginTypeWithConfig[] => {
                const pluginValues = Object.values(plugins)
                return pluginValues
                    .map((plugin, index) => {
                        let pluginConfig = pluginConfigs[plugin.id]
                        if (!pluginConfig) {
                            const config: Record<string, any> = {}
                            Object.entries(getConfigSchemaObject(plugin.config_schema)).forEach(
                                ([key, { default: def }]) => {
                                    config[key] = def
                                }
                            )

                            pluginConfig = {
                                id: undefined,
                                plugin: plugin.id,
                                enabled: false,
                                config: config,
                                order: pluginValues.length + index,
                            }
                        }
                        return { ...plugin, pluginConfig }
                    })
                    .sort((a, b) => a.pluginConfig.order - b.pluginConfig.order)
                    .map((plugin, index) => ({ ...plugin, order: index + 1 }))
            },
        ],
        installedPluginUrls: [
            (s) => [s.installedPlugins],
            (installedPlugins) => {
                const names: Record<string, boolean> = {}
                installedPlugins.forEach((plugin) => {
                    if (plugin.url) {
                        names[plugin.url.replace(/\/+$/, '')] = true
                    }
                })
                return names
            },
        ],
        uninstalledPlugins: [
            (s) => [s.installedPluginUrls, s.repository],
            (installedPluginUrls, repository) => {
                return Object.keys(repository)
                    .filter((url) => !installedPluginUrls[url.replace(/\/+$/, '')])
                    .map((url) => repository[url.replace(/\/+$/, '')])
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
    },

    events: ({ actions }) => ({
        afterMount: () => {
            actions.loadPlugins()
            actions.loadPluginConfigs()

            if (userLogic.values.user?.plugin_access.install) {
                actions.loadRepository()
            }
        },
    }),
})
