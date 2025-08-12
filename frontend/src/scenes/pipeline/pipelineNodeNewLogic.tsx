import { connect, kea, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { capitalizeFirstLetter } from 'lib/utils'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { Breadcrumb, PipelineStage, PipelineTab, PluginType, ProjectTreeRef } from '~/types'

import type { pipelineNodeNewLogicType } from './pipelineNodeNewLogicType'
import { loadPluginsFromUrl } from './utils'

export const NODE_STAGE_TO_PIPELINE_TAB: Partial<Record<PipelineStage, PipelineTab>> = {
    [PipelineStage.Transformation]: PipelineTab.Transformations,
    [PipelineStage.Destination]: PipelineTab.Destinations,
    [PipelineStage.SiteApp]: PipelineTab.SiteApps,
    [PipelineStage.Source]: PipelineTab.Sources,
}
export interface PipelineNodeNewLogicProps {
    /** Might be null if a non-existent stage is set in the URL. */
    stage: PipelineStage | null
    pluginId: number | null
    batchExportDestination: string | null
    hogFunctionId: string | null
    kind: string | null
}

export const pipelineNodeNewLogic = kea<pipelineNodeNewLogicType>([
    props({} as PipelineNodeNewLogicProps),
    connect(() => ({
        values: [userLogic, ['user']],
    })),
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

    selectors({
        loading: [(s) => [s.pluginsLoading], (pluginsLoading) => pluginsLoading],
        breadcrumbs: [
            (_, p) => [p.stage, p.pluginId, p.kind, p.batchExportDestination],
            (stage, pluginId, kind, batchDestination): Breadcrumb[] => {
                const parsedStage = stage ? stage.replace('-', ' ') : null

                return [
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
                        name: kind
                            ? `New ${capitalizeFirstLetter(kind)} source`
                            : pluginId
                              ? 'New'
                              : batchDestination
                                ? `New ${batchDestination} destination`
                                : `New ${parsedStage}`.trim(),
                    },
                ]
            },
        ],
        projectTreeRef: [
            (s) => [s.loading],
            (): ProjectTreeRef => ({
                type: 'hog_function/',
                ref: null,
            }),
        ],
    }),
])
