import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { actionToUrl, urlToAction } from 'kea-router'
import { canConfigurePlugins, canGloballyManagePlugins } from 'scenes/plugins/access'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature, Breadcrumb, PipelineStage, PipelineTab } from '~/types'

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

export type OperationType = 'new_or_enable' | 'edit_without_enable'
const ops = ['new_or_enable', 'edit_without_enable']

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
        notAllowedReasonByStageAndOperationType: [
            (s) => [s.canConfigurePlugins, s.user, s.hasAvailableFeature],
            (
                canConfigurePlugins,
                user,
                hasAvailableFeature
            ): Record<PipelineStage, Record<OperationType, string | undefined>> => {
                if (!canConfigurePlugins) {
                    return [
                        PipelineStage.ImportApp,
                        PipelineStage.SiteApp,
                        PipelineStage.Transformation,
                        PipelineStage.Destination,
                    ].reduce(
                        (acc, stage) => ({
                            ...acc,
                            [stage]: ops.reduce(
                                (acc, op) => ({ ...acc, [op]: `You do not have permission to change ${stage}s.` }),
                                {}
                            ),
                        }),
                        {} as Record<PipelineStage, Record<OperationType, string | undefined>>
                    )
                }
                return {
                    [PipelineStage.ImportApp]: ops.reduce(
                        (acc, op) => ({ ...acc, [op]: 'Legacy sources are deprecated.' }),
                        {} as Record<OperationType, string | undefined>
                    ),
                    [PipelineStage.SiteApp]: ops.reduce(
                        (acc, op) => ({ ...acc, [op]: undefined }),
                        {} as Record<OperationType, string | undefined>
                    ),
                    [PipelineStage.Transformation]: ops.reduce(
                        (acc, op) => ({ ...acc, [op]: undefined }),
                        {} as Record<OperationType, string | undefined>
                    ),
                    [PipelineStage.Destination]: {
                        new_or_enable:
                            user?.is_impersonated || hasAvailableFeature(AvailableFeature.DATA_PIPELINES)
                                ? undefined
                                : 'Data pipelines add-on is required for enabling new destinations',
                        edit_without_enable: undefined,
                    },
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
