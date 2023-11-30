import { actions, kea, path, reducers, selectors } from 'kea'
import { actionToUrl, urlToAction } from 'kea-router'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb, PipelineTabs } from '~/types'

import type { pipelineLogicType } from './pipelineLogicType'

export const singularName = (tab: PipelineTabs): string => {
    switch (tab) {
        case PipelineTabs.Filters:
            return 'filter'
        case PipelineTabs.Transformations:
            return 'transformation'
        case PipelineTabs.Destinations:
            return 'destination'
        default:
            return ''
    }
}

export const humanFriendlyTabName = (tab: PipelineTabs): string => {
    switch (tab) {
        case PipelineTabs.Filters:
            return 'Filters'
        case PipelineTabs.Transformations:
            return 'Transformations'
        case PipelineTabs.Destinations:
            return 'Destinations'
        case PipelineTabs.AppsManagement:
            return 'Apps Management'
    }
}

export const pipelineLogic = kea<pipelineLogicType>([
    path(['scenes', 'pipeline', 'pipelineLogic']),
    actions({
        setCurrentTab: (tab: PipelineTabs = PipelineTabs.Destinations) => ({ tab }),
    }),
    reducers({
        currentTab: [
            PipelineTabs.Destinations as PipelineTabs,
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
                actions.setCurrentTab(tab as PipelineTabs)
            }
        },
    })),
])
