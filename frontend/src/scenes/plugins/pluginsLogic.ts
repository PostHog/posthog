import { kea } from 'kea'
import { pluginsLogicType } from 'types/scenes/plugins/pluginsLogicType'
import api from 'lib/api'
import { PluginType } from '~/types'
import { PluginRepositoryEntry } from './types'

export const pluginsLogic = kea<pluginsLogicType<PluginType, PluginRepositoryEntry>>({
    actions: {
        editPlugin: (name: string | null) => ({ name }),
        saveEditedPlugin: (pluginConfig: Record<string, any>) => ({ pluginConfig }),
        uninstallPlugin: (name: string) => ({ name }),
        setCustomPluginUrl: (customPluginUrl: string) => ({ customPluginUrl }),
        installCustomPlugin: (customPluginUrl: string) => ({ customPluginUrl }),
        setCustomPluginError: (customPluginError: string) => ({ customPluginError }),
    },

    loaders: ({ values }) => ({
        plugins: [
            {} as Record<string, PluginType>,
            {
                loadPlugins: async () => {
                    const { results } = await api.get('api/plugin')
                    const plugins: Record<string, PluginType> = {}
                    for (const plugin of results as PluginType[]) {
                        plugins[plugin.name] = plugin
                    }
                    return plugins
                },
                installPlugin: async (repositoryEntry: PluginRepositoryEntry) => {
                    const { plugins } = values
                    const nextOrder = Math.max(
                        Object.values(plugins)
                            .map((p) => p.order || 1)
                            .sort()
                            .reverse()[0] || 0,
                        Object.keys(plugins).length + 1
                    )

                    const config: Record<string, any> = {}
                    if (repositoryEntry.config) {
                        for (const [key, { default: def }] of Object.entries(repositoryEntry.config)) {
                            config[key] = def || ''
                        }
                    }

                    const response = await api.create('api/plugin', {
                        name: repositoryEntry.name,
                        description: repositoryEntry.description,
                        url: repositoryEntry.url,
                        tag: repositoryEntry.tag,
                        enabled: false,
                        order: nextOrder,
                        config: config,
                        configSchema: repositoryEntry.config,
                    })

                    return { ...plugins, [response.name]: response }
                },
                saveEditedPlugin: async ({ pluginConfig }) => {
                    const { plugins, editingPlugin } = values

                    if (!editingPlugin) {
                        return plugins
                    }

                    const { __enabled: enabled, ...config } = pluginConfig

                    const response = await api.update(`api/plugin/${editingPlugin.id}`, {
                        enabled,
                        config,
                    })

                    return { ...plugins, [response.name]: response }
                },
                uninstallPlugin: async () => {
                    const { plugins, editingPlugin } = values
                    if (!editingPlugin) {
                        return plugins
                    }

                    await api.delete(`api/plugin/${editingPlugin.id}`)
                    const { [editingPlugin.name]: _discard, ...rest } = plugins // eslint-disable-line
                    return rest
                },
            },
        ],
        repository: [
            {} as Record<string, PluginRepositoryEntry>,
            {
                loadRepository: async () => {
                    const results = await api.get('api/plugin/repository')
                    const repository: Record<string, PluginRepositoryEntry> = {}
                    for (const plugin of results as PluginRepositoryEntry[]) {
                        repository[plugin.name] = plugin
                    }
                    return repository
                },
            },
        ],
    }),

    reducers: {
        editingPluginName: [
            null as string | null,
            {
                editPlugin: (_, { name }) => name,
                saveEditedPluginSuccess: () => null,
                uninstallPluginSuccess: () => null,
                installPluginSuccess: (_, { plugins }) => Object.keys(plugins).pop() || null,
            },
        ],
        customPluginUrl: [
            '',
            {
                setCustomPluginUrl: (_, { customPluginUrl }) => customPluginUrl,
                installPluginSuccess: () => '',
            },
        ],
        customPluginError: [
            null as null | string,
            {
                setCustomPluginError: (_, { customPluginError }) => customPluginError,
                setCustomPluginUrl: () => null,
                installCustomPlugin: () => null,
            },
        ],
        installingCustomPlugin: [
            false,
            {
                installCustomPlugin: () => true,
                setCustomPluginError: () => false,
                installPluginFailure: () => false,
                installPluginSuccess: () => false,
            },
        ],
    },

    selectors: {
        installedPlugins: [(s) => [s.plugins], (plugins) => Object.values(plugins).sort((a, b) => a.order - b.order)],
        uninstalledPlugins: [
            (s) => [s.plugins, s.repository],
            (plugins, repository) => {
                return Object.keys(repository)
                    .filter((name) => !plugins[name])
                    .map((name) => repository[name])
            },
        ],
        editingPlugin: [
            (s) => [s.editingPluginName, s.plugins],
            (editingPluginName, plugins) => (editingPluginName ? plugins[editingPluginName] : null),
        ],
    },

    events: ({ actions }) => ({
        afterMount: [actions.loadPlugins, actions.loadRepository],
    }),

    listeners: ({ actions, values }) => ({
        installCustomPlugin: async ({ customPluginUrl }) => {
            const match = customPluginUrl.match(/https?:\/\/(www\.|)github.com\/([^\/]+)\/([^\/]+)\/?$/)
            if (!match) {
                actions.setCustomPluginError('Must be in the format: https://github.com/user/repo')
                return
            }
            const [, , user, repo] = match

            const repoUrl = `https://api.github.com/repos/${user}/${repo}`
            const repoDetails: Record<string, any> | null = await window
                .fetch(repoUrl)
                .then((response) => response?.json())
                .catch(() => null)

            if (!repoDetails) {
                actions.setCustomPluginError(`Could not find repository: ${customPluginUrl}`)
                return
            }

            const tag: string = repoDetails['default_branch']
            const jsonUrl = `https://raw.githubusercontent.com/${user}/${repo}/${tag}/plugin.json`
            const json: PluginRepositoryEntry | null = await window
                .fetch(jsonUrl)
                .then((response) => response?.json())
                .catch(() => null)

            if (!json) {
                actions.setCustomPluginError(`Could not find plugin.json in repository: ${customPluginUrl}`)
                return
            }

            if (Object.values(values.plugins).find((p) => p.name === json.name)) {
                actions.setCustomPluginError(`Plugin with the name "${json.name}" already installed!`)
                return
            }

            actions.installPlugin({ ...json, tag })
        },
    }),
})
