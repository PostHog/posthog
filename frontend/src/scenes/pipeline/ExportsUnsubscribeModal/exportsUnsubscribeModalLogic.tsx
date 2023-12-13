import { actions, afterMount, connect, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { pluginsLogic } from 'scenes/plugins/pluginsLogic'

import { BatchExportConfiguration, PluginConfigTypeNew } from '~/types'

import type { exportsUnsubscribeModalLogicType } from './exportsUnsubscribeModalLogicType'

export const exportsUnsubscribeModalLogic = kea<exportsUnsubscribeModalLogicType>([
    path(['scenes', 'pipeline', 'exportsUnsubscribeModalLogic']),
    connect({ values: [pluginsLogic, ['plugins']] }),
    actions({
        openModal: true,
        closeModal: true,
    }),
    loaders(({ values }) => ({
        pluginConfigs: [
            {} as Record<number, PluginConfigTypeNew>,
            {
                loadPluginConfigs: async () => {
                    // TODO: need the api to give all the plugin configs for the organization that need to be disabled.
                    const pluginConfigs: Record<number, PluginConfigTypeNew> = {}
                    const results: PluginConfigTypeNew[] = await api.loadPaginatedResults(
                        `api/organizations/@current/plugins/exports_unsubscribe_configs`
                    )

                    for (const pluginConfig of results) {
                        pluginConfigs[pluginConfig.id] = {
                            ...pluginConfig,
                            // If this pluginConfig doesn't have a name of desciption, use the plugin's
                            name: pluginConfig.name || values.plugins[pluginConfig.plugin]?.name || 'Unknown app',
                            description: pluginConfig.description || values.plugins[pluginConfig.plugin]?.description,
                        }
                    }
                    return pluginConfigs
                },
            },
        ],
        batchExports: [
            {} as Record<number, BatchExportConfiguration>,
            {
                // TODO: need the api to give all the batch export configs for the organization that need to be disabled & their disabling action
            },
        ],
    })),
    selectors({
        loading: [
            (s) => [s.batchExportsLoading, s.pluginConfigsLoading],
            (batchExportsLoading, pluginConfigsLoading) => batchExportsLoading || pluginConfigsLoading,
        ],
        unsubscribeDisabled: [
            (s) => [s.pluginConfigs, s.batchExports],
            (pluginConfigs, batchExports) => pluginConfigs || batchExports,
        ],
    }),
    reducers({
        modalOpen: [
            false,
            {
                openModal: () => true,
                closeModal: () => false,
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadPluginConfigs()
    }),
])
