import { IconDatabase } from '@posthog/icons'
import { actions, afterMount, connect, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { pipelineAccessLogic } from 'scenes/pipeline/pipelineAccessLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { BatchExportConfiguration, PipelineStage, PluginConfigWithPluginInfoNew } from '~/types'

import { RenderApp } from '../../pipeline/utils'
import type { exportsUnsubscribeTableLogicType } from './exportsUnsubscribeTableLogicType'

export interface ItemToDisable {
    plugin_config_id: number | undefined // exactly one of plugin_config_id or batch_export_id is set
    batch_export_id: string | undefined
    url: string
    team_id: number
    name: string
    description: string | undefined
    icon: JSX.Element
    disabled: boolean
}

export const exportsUnsubscribeTableLogic = kea<exportsUnsubscribeTableLogicType>([
    path(['scenes', 'pipeline', 'ExportsUnsubscribeTableLogic']),
    connect({
        values: [pipelineAccessLogic, ['canConfigurePlugins'], userLogic, ['user']],
    }),

    actions({
        disablePlugin: (id: number) => ({ id }),
        pauseBatchExport: (id: string) => ({ id }),
    }),
    loaders(({ values }) => ({
        pluginConfigsToDisable: [
            {} as Record<PluginConfigWithPluginInfoNew['id'], PluginConfigWithPluginInfoNew>,
            {
                loadPluginConfigs: async () => {
                    const res = await api.get<PluginConfigWithPluginInfoNew[]>(
                        `api/organizations/@current/plugins/exports_unsubscribe_configs`
                    )
                    return Object.fromEntries(res.map((pluginConfig) => [pluginConfig.id, pluginConfig]))
                },
                disablePlugin: async ({ id }) => {
                    if (!values.canConfigurePlugins) {
                        return values.pluginConfigsToDisable
                    }
                    const response = await api.update(`api/plugin_config/${id}`, { enabled: false, deleted: true })
                    return { ...values.pluginConfigsToDisable, [id]: response }
                },
            },
        ],
        batchExportConfigs: [
            {} as Record<BatchExportConfiguration['id'], BatchExportConfiguration>,
            {
                loadBatchExportConfigs: async () => {
                    const res = await api.loadPaginatedResults<BatchExportConfiguration>(
                        `api/organizations/@current/batch_exports`
                    )
                    return Object.fromEntries(
                        res
                            .filter((batchExportConfig) => !batchExportConfig.paused)
                            .map((batchExportConfig) => [batchExportConfig.id, batchExportConfig])
                    )
                },
                pauseBatchExport: async ({ id }) => {
                    await api.create(`api/organizations/@current/batch_exports/${id}/pause`)
                    return { ...values.batchExportConfigs, [id]: { ...values.batchExportConfigs[id], paused: true } }
                },
            },
        ],
    })),
    selectors({
        loading: [
            (s) => [s.batchExportConfigsLoading, s.pluginConfigsToDisableLoading],
            (batchExportsLoading, pluginConfigsLoading) => batchExportsLoading || pluginConfigsLoading,
        ],
        unsubscribeDisabledReason: [
            (s) => [s.loading, s.pluginConfigsToDisable, s.batchExportConfigs],
            (loading, pluginConfigsToDisable, batchExportConfigs) => {
                // TODO: check for permissions first - that the user has access to all the projects for this org
                return loading
                    ? 'Loading...'
                    : Object.values(pluginConfigsToDisable).some((pluginConfig) => pluginConfig.enabled)
                    ? 'All apps above must be disabled first'
                    : Object.values(batchExportConfigs).some((batchExportConfig) => !batchExportConfig.paused)
                    ? 'All batch exports must be disabled first'
                    : null
            },
        ],
        itemsToDisable: [
            (s) => [s.pluginConfigsToDisable, s.batchExportConfigs],
            (pluginConfigsToDisable, batchExportConfigs) => {
                const pluginConfigs = Object.values(pluginConfigsToDisable).map((pluginConfig) => {
                    return {
                        plugin_config_id: pluginConfig.id,
                        team_id: pluginConfig.team_id,
                        name: pluginConfig.name,
                        description: pluginConfig.description,
                        icon: <RenderApp plugin={pluginConfig.plugin_info} imageSize="small" />,
                        disabled: !pluginConfig.enabled,
                        url: urls.pipelineNode(PipelineStage.Destination, pluginConfig.id),
                    } as ItemToDisable
                })
                const batchExports = Object.values(batchExportConfigs).map((batchExportConfig) => {
                    return {
                        batch_export_id: batchExportConfig.id,
                        team_id: batchExportConfig.team_id,
                        name: batchExportConfig.name,
                        description: batchExportConfig.destination.type,
                        icon: (
                            <IconDatabase
                                style={{
                                    fontSize: 30,
                                }}
                            />
                        ),
                        disabled: batchExportConfig.paused,
                        url: urls.pipelineNode(PipelineStage.Destination, batchExportConfig.id),
                    } as ItemToDisable
                })
                return [...pluginConfigs, ...batchExports]
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadPluginConfigs()
        actions.loadBatchExportConfigs()
    }),
])
