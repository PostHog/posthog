import { IconDatabase } from '@posthog/icons'
import { actions, afterMount, connect, kea, listeners, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { BatchExportConfiguration, PluginConfigWithPluginInfoNew } from '~/types'

import { RenderApp } from '../../data-pipelines/legacy-plugins/utils'
import type { exportsUnsubscribeTableLogicType } from './exportsUnsubscribeTableLogicType'

export interface ItemToDisable {
    plugin_config_id?: number // exactly one of these _id fields is set
    batch_export_id?: string
    hog_function_id?: string
    url: string
    team_id: number
    name: string
    description: string | undefined
    icon: JSX.Element
    disabled: boolean
}

export const exportsUnsubscribeTableLogic = kea<exportsUnsubscribeTableLogicType>([
    path(['scenes', 'pipeline', 'ExportsUnsubscribeTableLogic']),
    connect(() => ({
        // TODO: BEN FIX THIS
        values: [userLogic, ['user']],
        // actions: [pipelineDestinationsLogic({ types: DESTINATION_TYPES }), ['toggleNodeHogFunction']],
    })),

    actions({
        disablePlugin: (id: number) => ({ id }),
        pauseBatchExport: (id: string) => ({ id }),
        disableHogFunction: (id: string) => ({ id }),
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
            (pluginConfigsToDisable, batchExportConfigs): ItemToDisable[] => {
                const pluginConfigs = Object.values(pluginConfigsToDisable).map((pluginConfig) => {
                    return {
                        plugin_config_id: pluginConfig.id,
                        team_id: pluginConfig.team_id,
                        name: pluginConfig.name,
                        description: pluginConfig.description,
                        icon: <RenderApp plugin={pluginConfig.plugin_info} imageSize="small" />,
                        disabled: !pluginConfig.enabled,
                        url: urls.legacyPlugin(pluginConfig.id.toString()),
                    } satisfies ItemToDisable
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
                        url: urls.batchExport(batchExportConfig.id),
                    } satisfies ItemToDisable
                })
                // const hogFunctions = paidHogFunctions.map((hogFunction) => {
                //     return {
                //         hog_function_id: hogFunction.id,
                //         team_id: getCurrentTeamId(),
                //         name: hogFunction.name,
                //         description: hogFunction.description,
                //         icon: <HogFunctionIcon src={hogFunction.icon_url} size="small" />,
                //         disabled: false,
                //         url: urls.pipelineNode(PipelineStage.Destination, `hog-${hogFunction.id}`),
                //     } satisfies ItemToDisable
                // })
                return [...pluginConfigs, ...batchExports]
            },
        ],
    }),
    listeners(() => ({
        // disableHogFunction: ({ id }) => {
        //     const hogFunction = (values.paidHogFunctions ?? []).find((f) => f.id === id)
        //     // if (hogFunction) {
        //     //     actions.toggleNodeHogFunction(
        //     //         {
        //     //             name: hogFunction.name,
        //     //             enabled: true,
        //     //             stage: PipelineStage.Destination,
        //     //             interval: 'realtime',
        //     //             backend: PipelineBackend.HogFunction,
        //     //             id,
        //     //             hog_function: hogFunction,
        //     //         } as FunctionDestination,
        //     //         false
        //     //     )
        //     // }
        // },
    })),
    afterMount(({ actions }) => {
        actions.loadPluginConfigs()
        actions.loadBatchExportConfigs()
    }),
])
