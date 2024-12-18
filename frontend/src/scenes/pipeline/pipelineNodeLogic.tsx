import { actions, kea, key, path, props, reducers, selectors } from 'kea'
import { actionToUrl, urlToAction } from 'kea-router'
import { capitalizeFirstLetter } from 'lib/utils'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { ActivityFilters } from '~/layout/navigation-3000/sidepanel/panels/activity/activityForSceneLogic'
import { ActivityScope, Breadcrumb, PipelineNodeTab, PipelineStage } from '~/types'

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
type HogFunctionNodeId = {
    backend: PipelineBackend.HogFunction
    id: string
}
type ManagedSourceId = {
    backend: PipelineBackend.ManagedSource
    id: string
}
export type PipelineNodeLimitedType = PluginNodeId | BatchExportNodeId | HogFunctionNodeId | ManagedSourceId

export const pipelineNodeLogic = kea<pipelineNodeLogicType>([
    props({} as PipelineNodeLogicProps),
    key(({ id }) => id),
    path((id) => ['scenes', 'pipeline', 'pipelineNodeLogic', id]),
    actions({
        setCurrentTab: (tab: PipelineNodeTab = PipelineNodeTab.Configuration) => ({ tab }),
        setBreadcrumbTitle: (title: string) => ({ title }),
    }),
    reducers(() => ({
        currentTab: [
            PipelineNodeTab.Configuration as PipelineNodeTab,
            {
                setCurrentTab: (_, { tab }) => tab,
            },
        ],
        breadcrumbTitle: [
            '',
            {
                setBreadcrumbTitle: (_, { title }) => title,
            },
        ],
    })),
    selectors(() => ({
        breadcrumbs: [
            (s, p) => [p.id, p.stage, s.breadcrumbTitle],
            (id, stage, breadcrumbTitle): Breadcrumb[] => [
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
                    name: breadcrumbTitle,
                },
            ],
        ],

        activityFilters: [
            (s) => [s.node],
            (node): ActivityFilters | null => {
                return node.backend === PipelineBackend.Plugin
                    ? {
                          scope: ActivityScope.PLUGIN,
                          item_id: `${node.id}`,
                      }
                    : null
            },
        ],

        nodeBackend: [
            (s) => [s.node],
            (node): PipelineBackend => {
                return node.backend
            },
        ],
        node: [
            (_, p) => [p.id],
            (id): PipelineNodeLimitedType => {
                if (typeof id === 'string') {
                    if (id.indexOf('hog-') === 0) {
                        return { backend: PipelineBackend.HogFunction, id: `${id}`.replace('hog-', '') }
                    }

                    if (id.indexOf('managed') === 0) {
                        return { backend: PipelineBackend.ManagedSource, id: `${id}`.replace('managed-', '') }
                    }

                    return { backend: PipelineBackend.BatchExport, id }
                }

                return { backend: PipelineBackend.Plugin, id }
            },
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
    urlToAction(({ props, actions, values }) => ({
        [urls.pipelineNode(props.stage as PipelineStage, props.id, ':nodeTab')]: ({ nodeTab }) => {
            if (nodeTab !== values.currentTab && Object.values(PipelineNodeTab).includes(nodeTab as PipelineNodeTab)) {
                actions.setCurrentTab(nodeTab as PipelineNodeTab)
            }
        },
    })),
])
