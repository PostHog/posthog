import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { actionToUrl, urlToAction } from 'kea-router'
import { capitalizeFirstLetter } from 'lib/utils'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { ActivityFilters } from '~/layout/navigation-3000/sidepanel/panels/activity/activityForSceneLogic'
import { ActivityScope, Breadcrumb, PipelineTab } from '~/types'

import type { pipelineLogicType } from './pipelineLogicType'

export const humanFriendlyTabName = (tab: PipelineTab): string => {
    return capitalizeFirstLetter(tab).replace(/[-_]/g, ' ')
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
            (tab: PipelineTab): Breadcrumb[] => {
                return [
                    { key: Scene.Pipeline, name: 'Data pipeline' },
                    {
                        key: tab,
                        name: humanFriendlyTabName(tab),
                    },
                ]
            },
        ],

        activityFilters: [
            () => [],
            (): ActivityFilters | null => {
                return {
                    scope: ActivityScope.PLUGIN,
                }
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
