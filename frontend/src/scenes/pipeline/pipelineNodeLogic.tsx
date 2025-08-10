import { actions, kea, key, path, props, reducers, selectors } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { capitalizeFirstLetter } from 'lib/utils'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'
import { ActivityScope, Breadcrumb, PipelineNodeTab, PipelineStage, ProjectTreeRef } from '~/types'

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

export type PipelineNodeLimitedType = PluginNodeId | BatchExportNodeId | HogFunctionNodeId

export const pipelineNodeLogic = kea<pipelineNodeLogicType>([
    props({} as PipelineNodeLogicProps),
    key(({ id }) => id),
    path((id) => ['scenes', 'pipeline', 'pipelineNodeLogic', id]),
    actions({
        setCurrentTab: (tab: PipelineNodeTab = PipelineNodeTab.Configuration) => ({ tab }),
        setBreadcrumbTitle: (title: string) => ({ title }),
        setProjectTreeRef: (projectTreeRef: ProjectTreeRef) => ({ projectTreeRef }),
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
        projectTreeRef: [
            null as ProjectTreeRef | null,
            {
                setProjectTreeRef: (_, { projectTreeRef }) => projectTreeRef,
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

        [SIDE_PANEL_CONTEXT_KEY]: [
            (s) => [s.node],
            (node): SidePanelSceneContext | null => {
                return node.backend === PipelineBackend.Plugin
                    ? {
                          activity_scope: ActivityScope.PLUGIN,
                          activity_item_id: `${node.id}`,
                          //   access_control_resource: 'plugin',
                          //   access_control_resource_id: `${node.id}`,
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

            // Redirect managed sources to the new data warehouse source page
            if (
                typeof props.id === 'string' &&
                (props.id.startsWith('managed-') || props.id.startsWith('self-managed-'))
            ) {
                router.actions.replace(urls.dataWarehouseSource(props.id.toString()))
                return
            }

            // Set the project tree ref from the URL
            // Use the wildcard 'hog/' type format to match against all possible types without a mapping from the URL
            const path = router.values.location.pathname
            const match = path.match(/\/pipeline\/([^/]+)\/hog-([^/]+)\/?/)
            if (match) {
                const { projectTreeRef } = values
                const type = 'hog_function/'
                const ref = match[2]
                if (!projectTreeRef || projectTreeRef.type !== type || projectTreeRef.ref !== ref) {
                    actions.setProjectTreeRef({ type, ref })
                }
            }
        },
    })),
])
