import { actions, afterMount, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { Dayjs, dayjs } from 'lib/dayjs'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { ErrorTrackingGroup } from '~/queries/schema'
import { Breadcrumb } from '~/types'

import type { errorTrackingGroupSceneLogicType } from './errorTrackingGroupSceneLogicType'
import { errorTrackingLogic } from './errorTrackingLogic'
import { errorTrackingGroupEventsQuery, errorTrackingGroupQuery } from './queries'

export interface ErrorTrackingEvent {
    uuid: string
    timestamp: Dayjs
    properties: Record<string, any>
    person: {
        distinct_id: string
        uuid?: string
        created_at?: string
        properties?: Record<string, any>
    }
}

export interface ErrorTrackingGroupSceneLogicProps {
    fingerprint: ErrorTrackingGroup['fingerprint']
}

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

                    // ErrorTrackingQuery returns a list of groups
                    // when a fingerprint is supplied there will only be a single group
                    return response.results[0]
                },
            },
        ],
        events: [
            [] as ErrorTrackingEvent[],
            {
                loadEvents: async () => {
                    const response = await api.query(
                        errorTrackingGroupEventsQuery({
                            select: ['uuid', 'properties', 'timestamp', 'person'],
                            fingerprints: values.combinedFingerprints,
                            dateRange: values.dateRange,
                            filterTestAccounts: values.filterTestAccounts,
                            filterGroup: values.filterGroup,
                            offset: values.events.length,
                        })
                    )

                    return response.results.map((r) => ({
                        uuid: r[0],
                        properties: JSON.parse(r[1]),
                        timestamp: dayjs(r[2]),
                        person: r[3],
                    }))
                },
            },
        ],
    })),

    listeners(({ actions }) => ({
        loadGroupSuccess: () => {
            actions.loadEvents()
        },
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

        combinedFingerprints: [
            (s) => [s.group],
            (group): ErrorTrackingGroup['fingerprint'][] =>
                group ? [group.fingerprint, ...group.merged_fingerprints] : [],
        ],
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
