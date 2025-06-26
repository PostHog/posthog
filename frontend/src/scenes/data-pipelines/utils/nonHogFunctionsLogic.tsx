import { connect, kea, path } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { parseGithubRepoURL } from 'lib/utils'
import { sourceWizardLogic } from 'scenes/data-warehouse/new/sourceWizardLogic'
import { userLogic } from 'scenes/userLogic'

import { HogFunctionType, PluginConfigTypeNew, PluginType } from '~/types'

import { BATCH_EXPORT_ICON_MAP } from '../batch-exports/BatchExportIcon'
import type { nonHogFunctionsLogicType } from './nonHogFunctionsLogicType'

export const nonHogFunctionsLogic = kea<nonHogFunctionsLogicType>([
    path((key) => ['scenes', 'data-pipelines', 'utils', 'nonHogFunctionsLogic', key]),

    connect(() => ({
        values: [sourceWizardLogic, ['connectors'], featureFlagLogic, ['featureFlags'], userLogic, ['user']],
    })),

    loaders(() => ({
        hogFunctionPluginsDestinations: [
            null as HogFunctionType[] | null,
            {
                // NOTE: This is super temporary until we have fully migrated off of plugins
                loadHogFunctionPluginsDestinations: async () => {
                    const [pluginConfigs, plugins] = await Promise.all([
                        api.loadPaginatedResults<PluginConfigTypeNew>(
                            `api/projects/@current/pipeline_destination_configs`
                        ),
                        api.loadPaginatedResults<PluginType>(`api/organizations/@current/pipeline_destinations`),
                    ])

                    const pluginsById = Object.fromEntries(plugins.map((plugin) => [plugin.id, plugin]))

                    const hogfunctions: HogFunctionType[] = []

                    for (const pluginConfig of pluginConfigs) {
                        const plugin = pluginsById[pluginConfig.plugin]

                        let iconUrl = plugin.icon ?? 'static/images/plugin-default.png'

                        try {
                            const { user, repo, path } = parseGithubRepoURL(plugin.url || '')
                            iconUrl = `https://raw.githubusercontent.com/${user}/${repo}/${path || 'main'}/logo.png`
                        } catch {
                            // Do nothing
                        }

                        hogfunctions.push({
                            id: `plugin-${pluginConfig.id}`,
                            name: pluginConfig.name || plugin?.name || 'Unknown app',
                            description: pluginConfig.description || plugin?.description || '',
                            type: 'destination',
                            created_by: null,
                            created_at: '',
                            updated_at: pluginConfig.updated_at,
                            enabled: pluginConfig.enabled,
                            execution_order: undefined,
                            hog: '',
                            icon_url: iconUrl,
                        })
                    }

                    return hogfunctions
                },
            },
        ],

        hogFunctionPluginsSiteApps: [
            null as HogFunctionType[] | null,
            {
                // NOTE: This is super temporary until we have fully migrated off of plugins
                loadHogFunctionPluginsSiteApps: async () => {
                    const [pluginConfigs, plugins] = await Promise.all([
                        api.loadPaginatedResults<PluginConfigTypeNew>(
                            `api/projects/@current/pipeline_frontend_apps_configs`
                        ),
                        api.loadPaginatedResults<PluginType>(`api/organizations/@current/pipeline_frontend_apps`),
                    ])

                    const pluginsById = Object.fromEntries(plugins.map((plugin) => [plugin.id, plugin]))

                    const hogfunctions: HogFunctionType[] = []

                    for (const pluginConfig of pluginConfigs) {
                        const plugin = pluginsById[pluginConfig.plugin]

                        let iconUrl = plugin.icon ?? 'static/images/plugin-default.png'

                        try {
                            const { user, repo, path } = parseGithubRepoURL(plugin.url || '')
                            iconUrl = `https://raw.githubusercontent.com/${user}/${repo}/${path || 'main'}/logo.png`
                        } catch {
                            // Do nothing
                        }

                        hogfunctions.push({
                            id: `plugin-${pluginConfig.id}`,
                            name: pluginConfig.name || plugin?.name || 'Unknown app',
                            description: pluginConfig.description || plugin?.description || '',
                            type: 'destination',
                            created_by: null,
                            created_at: '',
                            updated_at: pluginConfig.updated_at,
                            enabled: pluginConfig.enabled,
                            execution_order: undefined,
                            hog: '',
                            icon_url: iconUrl,
                        })
                    }

                    return hogfunctions
                },
            },
        ],

        hogFunctionBatchExports: [
            null as HogFunctionType[] | null,
            {
                loadHogFunctionBatchExports: async () => {
                    const response = await api.batchExports.list()
                    const results = response.results
                    const hogFunctions: HogFunctionType[] = []

                    for (const batchExport of results) {
                        hogFunctions.push({
                            id: `batch-export-${batchExport.id}`,
                            name: batchExport.name,
                            description: `${batchExport.destination.type} batch export`,
                            type: 'destination',
                            created_by: null,
                            created_at: batchExport.created_at,
                            updated_at: batchExport.created_at,
                            enabled: !batchExport.paused,
                            hog: '',
                            icon_url: BATCH_EXPORT_ICON_MAP[batchExport.destination.type],
                            execution_order: undefined,
                        })
                    }

                    return hogFunctions
                },
            },
        ],
    })),
])
