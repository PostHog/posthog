import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { actionToUrl, urlToAction } from 'kea-router'
import { canConfigurePlugins, canGloballyManagePlugins } from 'scenes/plugins/access'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature, Breadcrumb, PipelineTab } from '~/types'

import type { pipelineLogicType } from './pipelineLogicType'

export const humanFriendlyTabName = (tab: PipelineTab): string => {
    switch (tab) {
        case PipelineTab.Overview:
            return 'Overview'
        case PipelineTab.Transformations:
            return 'Transformations'
        case PipelineTab.Destinations:
            return 'Destinations'
        case PipelineTab.SiteApps:
            return 'Site Apps'
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
        // This is currently an organization level setting but might in the future be user level
        // it's better to add the permission checks everywhere now
        canGloballyManagePlugins: [(s) => [s.user], (user) => canGloballyManagePlugins(user?.organization)],
        canConfigurePlugins: [(s) => [s.user], (user) => canConfigurePlugins(user?.organization)],
        canEnableNewDestinations: [
            (s) => [s.user, s.hasAvailableFeature],
            (user, hasAvailableFeature) =>
                user?.is_impersonated ||
                (canConfigurePlugins(user?.organization) && hasAvailableFeature(AvailableFeature.DATA_PIPELINES)),
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
