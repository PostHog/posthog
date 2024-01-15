import { actions, kea, path, reducers, selectors } from 'kea'
import { actionToUrl, urlToAction } from 'kea-router'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb, PipelineTab } from '~/types'

import type { pipelineLogicType } from './pipelineLogicType'

export const humanFriendlyTabName = (tab: PipelineTab): string => {
    switch (tab) {
        case PipelineTab.Overview:
            return 'Overview'
        case PipelineTab.Filters:
            return 'Filters'
        case PipelineTab.Transformations:
            return 'Transformations'
        case PipelineTab.Destinations:
            return 'Destinations'
        case PipelineTab.AppsManagement:
            return 'Apps management'
    }
}

export const pipelineLogic = kea<pipelineLogicType>([
    path(['scenes', 'pipeline', 'pipelineLogic']),
    actions({
        setCurrentTab: (tab: PipelineTab = PipelineTab.Destinations) => ({ tab }),
    }),
    reducers({
        currentTab: [
            PipelineTab.Destinations as PipelineTab,
            {
                setCurrentTab: (_, { tab }) => tab,
            },
        ],
    }),
    selectors(() => ({
        breadcrumbs: [
            (s) => [s.currentTab],
            (tab): Breadcrumb[] => {
                return [
                    { key: Scene.Pipeline, name: 'Data pipeline' },
                    {
                        key: tab,
                        name: humanFriendlyTabName(tab),
                    },
                ]
            },
        ],
    })),
    actionToUrl(({ values }) => {
        return {
            setCurrentTab: () => [urls.pipeline(values.currentTab)],
        }
    }),
    urlToAction(({ actions, values }) => ({
        '/pipeline/:tab': ({ tab }) => {
            if (tab !== values.currentTab) {
                actions.setCurrentTab(tab as PipelineTab)
            }
        },
    })),
])
