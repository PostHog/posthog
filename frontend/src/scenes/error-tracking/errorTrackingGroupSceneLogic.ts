import { actions, afterMount, connect, kea, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { ErrorTrackingGroup } from '~/queries/schema'
import { Breadcrumb } from '~/types'

import type { errorTrackingGroupSceneLogicType } from './errorTrackingGroupSceneLogicType'
import { errorTrackingLogic } from './errorTrackingLogic'
import { errorTrackingGroupQuery } from './queries'

export interface ErrorTrackingGroupSceneLogicProps {
    fingerprint: string[]
}

export enum ErrorGroupTab {
    Overview = 'overview',
    Breakdowns = 'breakdowns',
}

export type ErrorTrackingGroupEvent = {
    uuid: string
    properties: string
    timestamp: string
    person: {
        distinct_id: string
        uuid?: string
        created_at?: string
        properties?: Record<string, any>
    }
}

export const errorTrackingGroupSceneLogic = kea<errorTrackingGroupSceneLogicType>([
    path((key) => ['scenes', 'error-tracking', 'errorTrackingGroupSceneLogic', key]),
    props({} as ErrorTrackingGroupSceneLogicProps),

    connect({
        values: [errorTrackingLogic, ['dateRange', 'filterTestAccounts', 'filterGroup']],
    }),

    actions({
        setErrorGroupTab: (tab: ErrorGroupTab) => ({ tab }),
        loadMoreErrors: true,
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
        group: [
            null as ErrorTrackingGroup | null,
            {
                loadGroup: async () => {
                    const response = await api.query(
                        errorTrackingGroupQuery({
                            fingerprint: props.fingerprint,
                            dateRange: values.dateRange,
                            filterTestAccounts: values.filterTestAccounts,
                            filterGroup: values.filterGroup,
                        })
                    )
                    return response.results[0]
                },
                loadMoreErrors: async () => {
                    if (values.group?.events) {
                        const existingEvents = values.group.events

                        const response = await api.query(
                            errorTrackingGroupQuery({
                                fingerprint: props.fingerprint,
                                dateRange: values.dateRange,
                                filterTestAccounts: values.filterTestAccounts,
                                filterGroup: values.filterGroup,
                                offset: existingEvents.length || 0,
                            })
                        )

                        const events = values.group.events
                        const newEvents = response.results[0].events || []
                        return { ...values.group, events: [...events, ...newEvents] }
                    }
                    return values.group
                },
            },
        ],
    })),

    selectors({
        breadcrumbs: [
            (s) => [s.group],
            (group): Breadcrumb[] => {
                const exceptionType = group?.exception_type || 'Unknown Type'
                return [
                    {
                        key: Scene.ErrorTracking,
                        name: 'Error tracking',
                        path: urls.errorTracking(),
                    },
                    {
                        key: [Scene.ErrorTrackingGroup, exceptionType],
                        name: exceptionType,
                    },
                ]
            },
        ],

        events: [(s) => [s.group], (group) => (group?.events || []) as ErrorTrackingGroupEvent[]],
    }),

    actionToUrl(({ values }) => ({
        setErrorGroupTab: () => {
            const searchParams = router.values.searchParams

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
        actions.loadGroup()
    }),
])
