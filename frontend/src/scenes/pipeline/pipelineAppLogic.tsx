import { kea, reducers, path, props, key, actions, selectors } from 'kea'

import type { pipelineAppLogicType } from './pipelineAppLogicType'
import { Breadcrumb, PipelineAppTabs } from '~/types'
import { urls } from 'scenes/urls'
import { actionToUrl, urlToAction } from 'kea-router'
import { Scene } from 'scenes/sceneTypes'

export interface PipelineAppLogicProps {
    id: number
}

export const pipelineAppLogic = kea<pipelineAppLogicType>([
    props({} as PipelineAppLogicProps),
    key(({ id }) => id),
    path((id) => ['scenes', 'pipeline', 'pipelineAppLogic', id]),
    actions({
        setCurrentTab: (tab: PipelineAppTabs = PipelineAppTabs.Configuration) => ({ tab }),
    }),
    reducers({
        currentTab: [
            PipelineAppTabs.Configuration as PipelineAppTabs,
            {
                setCurrentTab: (_, { tab }) => tab,
            },
        ],
    }),
    selectors({
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: Scene.Pipeline,
                    name: 'Pipeline',
                    path: urls.pipeline(),
                },
                {
                    key: 'todo',
                    name: 'App name',
                },
            ],
        ],
    }),
    actionToUrl(({ values, props }) => {
        return {
            setCurrentTab: () => [urls.pipelineApp(props.id, values.currentTab)],
        }
    }),
    urlToAction(({ actions, values }) => ({
        '/pipeline/:id/:tab': ({ tab }) => {
            if (tab !== values.currentTab) {
                actions.setCurrentTab(tab as PipelineAppTabs)
            }
        },
    })),
])
