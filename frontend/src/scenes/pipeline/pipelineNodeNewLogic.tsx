import { kea, path, props, selectors } from 'kea'
import { capitalizeFirstLetter } from 'lib/utils'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb, PipelineStage, PipelineTab } from '~/types'

import type { pipelineNodeNewLogicType } from './pipelineNodeNewLogicType'

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
}

export const pipelineNodeNewLogic = kea<pipelineNodeNewLogicType>([
    props({} as PipelineNodeNewLogicProps),
    path((pluginIdOrBatchExportDestination) => [
        'scenes',
        'pipeline',
        'pipelineNodeNewLogic',
        pluginIdOrBatchExportDestination,
    ]),
    selectors(() => ({
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
                    // TODO: use the plugin name
                    key: pluginId || batchDestination || 'Unknown',
                    name: pluginId ? pluginId.toString() : batchDestination ?? 'Options',
                },
            ],
        ],
    })),
])
