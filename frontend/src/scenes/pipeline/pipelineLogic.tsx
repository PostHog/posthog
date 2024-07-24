import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { actionToUrl, urlToAction } from 'kea-router'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { Breadcrumb, PipelineTab } from '~/types'

import type { pipelineLogicType } from './pipelineLogicType'

export const humanFriendlyTabName = (tab: PipelineTab): string => {
    switch (tab) {
        case PipelineTab.Overview:
            return 'Overview'
        case PipelineTab.Transformations:
            return 'Transformations'
        case PipelineTab.Destinations:
            return 'Destinations'
        case PipelineTab.DataImport:
            return 'Data import'
        case PipelineTab.SiteApps:
            return 'Site apps'
        case PipelineTab.ImportApps:
            return 'Legacy sources'
        case PipelineTab.AppsManagement:
            return 'Apps management'
    }
}

export const pipelineLogic = kea<pipelineLogicType>([
    path(['scenes', 'pipeline', 'pipelineLogic']),
    connect({
        values: [userLogic, ['user', 'hasAvailableFeature']],
    }),
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
