import { actions, connect, kea, key, path, props, reducers, selectors } from 'kea'
import { actionToUrl, urlToAction } from 'kea-router'
import { capitalizeFirstLetter } from 'lib/utils'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { Breadcrumb, PipelineNodeTab, PipelineStage } from '~/types'

import { pipelineBatchExportConfigurationLogic } from './pipelineBatchExportConfigurationLogic'
import type { pipelineNodeLogicType } from './pipelineNodeLogicType'
import { NODE_STAGE_TO_PIPELINE_TAB } from './pipelineNodeNewLogic'
import { pipelinePluginConfigurationLogic } from './pipelinePluginConfigurationLogic'
import { convertToPipelineNode, PipelineBackend, PipelineNode } from './types'

export interface PipelineNodeLogicProps {
    id: number | string
    /** Might be null if a non-existent stage is set in th URL. */
    stage: PipelineStage | null
}

type PluginNodeId = {
    backend: PipelineBackend.Plugin
    id: number
    name: 'new'
}
type BatchExportNodeId = {
    backend: PipelineBackend.BatchExport
    id: string
    name: 'new'
}
export type PipelineNodeType = PluginNodeId | BatchExportNodeId | PipelineNode

export const pipelineNodeLogic = kea<pipelineNodeLogicType>([
    props({} as PipelineNodeLogicProps),
    key(({ id }) => id),
    path((id) => ['scenes', 'pipeline', 'pipelineNodeLogic', id]),
    connect((props: PipelineNodeLogicProps) => ({
        values: [
            teamLogic,
            ['currentTeamId'],
            pipelinePluginConfigurationLogic({
                stage: props.stage,
                pluginConfigId: typeof props.id === 'string' ? null : props.id,
                pluginId: null,
            }),
            ['pluginConfig'],
            pipelineBatchExportConfigurationLogic({
                id: typeof props.id === 'string' ? props.id : null,
                service: null,
            }),
            ['batchExportConfig'],
        ],
    })),
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
            (s, p) => [p.id, p.stage, s.node],
            (id, stage, node): Breadcrumb[] => [
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
                    name: node.name,
                },
            ],
        ],
        node: [
            (s, p) => [p.id, p.stage, s.pluginConfig, s.batchExportConfig],
            (id, stage, pluginConfig, batchExportDestination): PipelineNodeType => {
                if (stage && pluginConfig) {
                    return convertToPipelineNode(pluginConfig, stage)
                }
                if (batchExportDestination) {
                    return convertToPipelineNode(batchExportDestination, PipelineStage.Destination)
                }
                // No existing Node found just backend and id
                return typeof id === 'string'
                    ? { backend: PipelineBackend.BatchExport, id: id, name: 'new' }
                    : { backend: PipelineBackend.Plugin, id: id, name: 'new' }
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
