import { actions, afterMount, connect, kea, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb, EventType } from '~/types'

import type { errorTrackingGroupSceneLogicType } from './errorTrackingGroupSceneLogicType'
import { errorTrackingLogic } from './errorTrackingLogic'
import { errorTrackingGroupQuery } from './queries'

export interface ErrorTrackingGroupSceneLogicProps {
    id: string
}

export type ExceptionEventType = Pick<EventType, 'id' | 'properties' | 'timestamp' | 'person'>

export enum ErrorGroupTab {
    Overview = 'overview',
    Breakdowns = 'breakdowns',
}

export const errorTrackingGroupSceneLogic = kea<errorTrackingGroupSceneLogicType>([
    path((key) => ['scenes', 'error-tracking', 'errorTrackingGroupSceneLogic', key]),
    props({} as ErrorTrackingGroupSceneLogicProps),

    connect({
        values: [errorTrackingLogic, ['dateRange', 'filterTestAccounts', 'filterGroup']],
    }),

    actions({
        setErrorGroupTab: (tab: ErrorGroupTab) => ({ tab }),
    }),

    reducers(() => ({
        errorGroupTab: [
            ErrorGroupTab.Overview as ErrorGroupTab,
            {
                setErrorGroupTab: (_, { tab }) => tab,
            },
        ],
    })),

    loaders(({ props, values }) => ({
        events: [
            [] as ExceptionEventType[],
            {
                loadEvents: async () => {
                    const response = await api.query(
                        errorTrackingGroupQuery({
                            fingerprint: props.id,
                            dateRange: values.dateRange,
                            filterTestAccounts: values.filterTestAccounts,
                            filterGroup: values.filterGroup,
                        })
                    )

                    return response.results.map((r) => ({
                        id: r[0],
                        properties: JSON.parse(r[1]),
                        timestamp: r[2],
                        person: r[3],
                    }))
                },
            },
        ],
    })),

    selectors({
        breadcrumbs: [
            (_, p) => [p.id],
            (id): Breadcrumb[] => {
                return [
                    {
                        key: Scene.ErrorTracking,
                        name: 'Error tracking',
                        path: urls.errorTracking(),
                    },
                    {
                        key: [Scene.ErrorTrackingGroup, id],
                        name: id,
                    },
                ]
            },
        ],
    }),

    actionToUrl(({ values }) => ({
        setErrorGroupTab: () => {
            const searchParams = {}

            if (values.errorGroupTab != ErrorGroupTab.Overview) {
                searchParams['tab'] = values.errorGroupTab
            }

            return [router.values.location.pathname, searchParams]
        },
    })),

    urlToAction(({ actions }) => ({
        [urls.errorTrackingGroup('*')]: (_, searchParams) => {
            if (searchParams.tab) {
                actions.setErrorGroupTab(searchParams.tab)
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadEvents()
    }),
])
