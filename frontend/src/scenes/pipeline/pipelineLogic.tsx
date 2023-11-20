import { actions, kea, path, reducers, selectors } from 'kea'
import type { pipelineLogicType } from './pipelineLogicType'
import { actionToUrl, urlToAction } from 'kea-router'
import { urls } from 'scenes/urls'
import { Breadcrumb, PipelineTabs } from '~/types'
import { Scene } from 'scenes/sceneTypes'

export const singularName = (tab: PipelineTabs): string => {
    switch (tab) {
        case PipelineTabs.Filters:
            return 'filter'
        case PipelineTabs.Transformations:
            return 'transformation'
        case PipelineTabs.Destinations:
            return 'destination'
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
