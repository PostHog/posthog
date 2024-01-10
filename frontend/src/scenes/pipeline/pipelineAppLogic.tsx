import { actions, kea, key, path, props, reducers, selectors } from 'kea'
import { actionToUrl, urlToAction } from 'kea-router'
import { capitalizeFirstLetter } from 'lib/utils'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb, PipelineAppTabs, PipelineTabs } from '~/types'

import type { pipelineAppLogicType } from './pipelineAppLogicType'

export interface PipelineAppLogicProps {
    id: number
    kind: PipelineTabs
}

export const pipelineAppLogic = kea<pipelineAppLogicType>([
    props({} as PipelineAppLogicProps),
    key(({ id }) => id),
    path((id) => ['scenes', 'pipeline', 'pipelineAppLogic', id]),
    actions({
        setCurrentTab: (tab: PipelineAppTabs = PipelineAppTabs.Configuration) => ({ tab }),
        setKind: (kind: PipelineTabs) => ({ kind }),
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
            (_, p) => [p.kind],
            (kind): Breadcrumb[] => [
                {
                    key: Scene.Pipeline,
                    name: 'Data pipeline',
                    path: urls.pipeline(),
                },
                {
                    key: 'Kind',
                    name: capitalizeFirstLetter(kind),
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
            setCurrentTab: () => [urls.pipelineApp(props.kind, props.id, values.currentTab)],
        }
    }),
    urlToAction(({ actions, values }) => ({
        '/pipeline/:kind/:id/:tab': ({ tab }) => {
            if (tab !== values.currentTab && Object.values(PipelineAppTabs).includes(tab as PipelineAppTabs)) {
                actions.setCurrentTab(tab as PipelineAppTabs)
            }
        },
    })),
])
