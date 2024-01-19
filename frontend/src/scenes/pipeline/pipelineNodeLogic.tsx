import { actions, afterMount, connect, kea, key, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { actionToUrl, urlToAction } from 'kea-router'
import api from 'lib/api'
import { capitalizeFirstLetter } from 'lib/utils'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb, PipelineNodeTab, PipelineStage } from '~/types'

import { pipelineDestinationsLogic } from './destinationsLogic'
import type { pipelineNodeLogicType } from './pipelineNodeLogicType'
import { convertToPipelineNode, PipelineBackend, PipelineNode } from './types'

export interface PipelineNodeLogicProps {
    id: number | string
    /** Might be null if a non-existent stage is set in th URL. */
    stage: PipelineStage | null
}

export const pipelineNodeLogic = kea<pipelineNodeLogicType>([
    props({} as PipelineNodeLogicProps),
    key(({ id }) => id),
    path((id) => ['scenes', 'pipeline', 'pipelineNodeLogic', id]),
    connect(() => ({
        values: [pipelineDestinationsLogic, ['plugins', 'pluginsLoading', 'pluginConfigs', 'pluginConfigsLoading']],
    })),
    actions({
        setCurrentTab: (tab: PipelineNodeTab = PipelineNodeTab.Configuration) => ({ tab }),
        loadNode: true,
    }),
    reducers({
        currentTab: [
            PipelineNodeTab.Configuration as PipelineNodeTab,
            {
                setCurrentTab: (_, { tab }) => tab,
            },
        ],
    }),
    loaders(({ props }) => ({
        node: [
            null as PipelineNode | null,
            {
                loadNode: async (_, breakpoint) => {
                    if (!props.stage) {
                        return null
                    }
                    let node: PipelineNode
                    if (typeof props.id === 'string') {
                        if (props.stage !== PipelineStage.Destination) {
                            return null
                        }
                        const batchExport = await api.batchExports.get(props.id)
                        node = convertToPipelineNode(batchExport, props.stage)
                    } else {
                        const pluginConfig = await api.pluginConfigs.get(props.id)
                        node = convertToPipelineNode(pluginConfig, props.stage)
                    }
                    breakpoint()
                    return node
                },
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
                    name: stage ? capitalizeFirstLetter(stage) : 'Unknown',
                    path: urls.pipeline(),
                },
                {
                    key: [Scene.PipelineNode, id],
                    name: node ? node.name || 'Unnamed' : 'Unknown',
                },
            ],
        ],
        nodeBackend: [
            (_, p) => [p.id],
            (id): PipelineBackend => (typeof id === 'string' ? PipelineBackend.BatchExport : PipelineBackend.Plugin),
        ],
        tabs: [
            (_, p) => [p.id],
            (id) => {
                const tabs = Object.values(PipelineNodeTab)
                if (typeof id === 'string') {
                    // Batch export
                    return tabs.filter((t) => t !== PipelineNodeTab.History)
                }
                return tabs
            },
        ],
        id: [(_, p) => [p.id], (id) => id],
        stage: [(_, p) => [p.stage], (stage) => stage],
    })),
    forms({
        configuration: {
            // TODO: Validate that required fields are filled in
            submit: () => {
                // TODO
            },
        },
    }),
    actionToUrl(({ values, props }) => {
        return {
            setCurrentTab: () => [urls.pipelineNode(props.stage as PipelineStage, props.id, values.currentTab)],
        }
    }),
    urlToAction(({ actions, values }) => ({
        '/pipeline/:stageTab/:id/:appTab': ({ appTab }) => {
            if (appTab !== values.currentTab && Object.values(PipelineNodeTab).includes(appTab as PipelineNodeTab)) {
                actions.setCurrentTab(appTab as PipelineNodeTab)
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadNode()
    }),
])
