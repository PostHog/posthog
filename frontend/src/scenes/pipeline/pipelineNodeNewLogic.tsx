import { connect, kea, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { capitalizeFirstLetter } from 'lib/utils'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import {
    BATCH_EXPORT_SERVICE_NAMES,
    BatchExportService,
    Breadcrumb,
    PipelineStage,
    PipelineTab,
    PluginType,
} from '~/types'

import type { pipelineNodeNewLogicType } from './pipelineNodeNewLogicType'
import { loadPluginsFromUrl } from './utils'

export const NODE_STAGE_TO_PIPELINE_TAB: Partial<Record<PipelineStage, PipelineTab>> = {
    [PipelineStage.Transformation]: PipelineTab.Transformations,
    [PipelineStage.Destination]: PipelineTab.Destinations,
    [PipelineStage.SiteApp]: PipelineTab.SiteApps,
}
export interface PipelineNodeNewLogicProps {
    /** Might be null if a non-existent stage is set in the URL. */
    stage: PipelineStage | null
    pluginId: number | null
    batchExportDestination: string | null
    hogFunctionId: string | null
}

export const pipelineNodeNewLogic = kea<pipelineNodeNewLogicType>([
    props({} as PipelineNodeNewLogicProps),
    connect({
        values: [userLogic, ['user']],
    }),
    path((id) => ['scenes', 'pipeline', 'pipelineNodeNewLogic', id]),

    loaders({
        plugins: [
            {} as Record<number, PluginType>,
            {
                loadPlugins: async () => {
                    return loadPluginsFromUrl('api/organizations/@current/pipeline_destinations')
                },
            },
        ],
    }),

    selectors(() => ({
        loading: [(s) => [s.pluginsLoading], (pluginsLoading) => pluginsLoading],
        breadcrumbs: [
            (_, p) => [p.stage, p.pluginId, p.batchExportDestination],
            (stage, pluginId, batchDestination): Breadcrumb[] => [
                {
                    key: Scene.Pipeline,
                    name: 'Data pipeline',
                    path: urls.pipeline(),
                },
                {
                    key: stage || 'unknown',
                    name: stage ? capitalizeFirstLetter(NODE_STAGE_TO_PIPELINE_TAB[stage] || '') : 'Unknown',
                    path: urls.pipeline(stage ? NODE_STAGE_TO_PIPELINE_TAB[stage] : undefined),
                },
                {
                    key: pluginId || batchDestination || 'Unknown',
                    name: pluginId ? 'New' : batchDestination ? `New ${batchDestination} destination` : 'New',
                },
            ],
        ],
        batchExportServiceNames: [
            (s) => [s.user],
            (user): BatchExportService['type'][] => {
                // HTTP is currently only used for Cloud to Cloud migrations and shouldn't be accessible to users
                const services: BatchExportService['type'][] = BATCH_EXPORT_SERVICE_NAMES.filter(
                    (service) => service !== 'HTTP'
                ) as BatchExportService['type'][]
                if (user?.is_impersonated || user?.is_staff) {
                    services.push('HTTP')
                }
                return services
            },
        ],
    })),
])
