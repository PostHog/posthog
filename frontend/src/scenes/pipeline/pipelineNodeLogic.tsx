import { actions, kea, key, path, props, reducers, selectors } from 'kea'
import { actionToUrl, urlToAction } from 'kea-router'
import { capitalizeFirstLetter } from 'lib/utils'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb, PipelineNodeTab, PipelineStage } from '~/types'

import type { pipelineNodeLogicType } from './pipelineNodeLogicType'
import { NODE_STAGE_TO_PIPELINE_TAB } from './pipelineNodeNewLogic'
import { PipelineBackend } from './types'

export interface PipelineNodeLogicProps {
    id: number | string
    /** Might be null if a non-existent stage is set in th URL. */
    stage: PipelineStage | null
}

type PluginNodeId = {
    backend: PipelineBackend.Plugin
    id: number
}
type BatchExportNodeId = {
    backend: PipelineBackend.BatchExport
    id: string
}
export type PipelineNodeLimitedType = PluginNodeId | BatchExportNodeId

export const pipelineNodeLogic = kea<pipelineNodeLogicType>([
    props({} as PipelineNodeLogicProps),
    key(({ id }) => id),
    path((id) => ['scenes', 'pipeline', 'pipelineNodeLogic', id]),
    actions({
        setCurrentTab: (tab: PipelineNodeTab = PipelineNodeTab.Configuration) => ({ tab }),
    }),
    reducers(() => ({
        currentTab: [
            PipelineNodeTab.Configuration as PipelineNodeTab,
            {
                setCurrentTab: (_, { tab }) => tab,
            },
        ],
    })),
    selectors(() => ({
        breadcrumbs: [
            (_, p) => [p.id, p.stage],
            (id, stage): Breadcrumb[] => [
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
                    key: [Scene.PipelineNode, id],
                    name: '',
                },
            ],
        ],
        node: [
            (_, p) => [p.id],
            (id): PipelineNodeLimitedType => {
                return typeof id === 'string'
                    ? { backend: PipelineBackend.BatchExport, id: id }
                    : { backend: PipelineBackend.Plugin, id: id }
            },
        ],
        nodeBackend: [
            (_, p) => [p.id],
            (id): PipelineBackend => (typeof id === 'string' ? PipelineBackend.BatchExport : PipelineBackend.Plugin),
        ],
        tabs: [
            (s) => [s.nodeBackend],
            (nodeBackend) => {
                const tabs = Object.values(PipelineNodeTab)
                if (nodeBackend === PipelineBackend.BatchExport) {
                    return tabs.filter((t) => t !== PipelineNodeTab.History)
                }
                return tabs
            },
        ],
        id: [(_, p) => [p.id], (id) => id],
        stage: [(_, p) => [p.stage], (stage) => stage],
    })),
    actionToUrl(({ values, props }) => {
        return {
            setCurrentTab: () => [urls.pipelineNode(props.stage as PipelineStage, props.id, values.currentTab)],
        }
    }),
    urlToAction(({ actions, values }) => ({
        '/pipeline/:stage/:id/:nodeTab': ({ nodeTab }) => {
            if (nodeTab !== values.currentTab && Object.values(PipelineNodeTab).includes(nodeTab as PipelineNodeTab)) {
                actions.setCurrentTab(nodeTab as PipelineNodeTab)
            }
        },
    })),
])
