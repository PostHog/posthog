import { actions, connect, kea, key, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { Dayjs } from 'lib/dayjs'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { ErrorTrackingIssue } from '~/queries/schema'
import { Breadcrumb, EventType } from '~/types'

import type { errorTrackingIssueSceneLogicType } from './errorTrackingIssueSceneLogicType'
import { errorTrackingLogic } from './errorTrackingLogic'
import { errorTrackingIssueEventsQuery, errorTrackingIssueQuery } from './queries'

export interface ErrorTrackingEvent {
    uuid: string
    timestamp: Dayjs
    properties: EventType['properties']
    person: {
        distinct_id: string
        uuid?: string
        created_at?: string
        properties?: Record<string, any>
    }
}

export interface ErrorTrackingIssueSceneLogicProps {
    id: ErrorTrackingIssue['id']
}

export enum IssueTab {
    Overview = 'overview',
    Events = 'events',
    Breakdowns = 'breakdowns',
}

export const errorTrackingIssueSceneLogic = kea<errorTrackingIssueSceneLogicType>([
    path((key) => ['scenes', 'error-tracking', 'errorTrackingIssueSceneLogic', key]),
    props({} as ErrorTrackingIssueSceneLogicProps),
    key((props) => props.id),

    connect({
        values: [errorTrackingLogic, ['dateRange', 'filterTestAccounts', 'filterGroup']],
    }),

    actions({
        setTab: (tab: IssueTab) => ({ tab }),
        setActiveEventUUID: (uuid: ErrorTrackingEvent['uuid']) => ({ uuid }),
        setIssue: (issue: ErrorTrackingIssue) => ({ issue }),
        updateIssue: (issue: Partial<Pick<ErrorTrackingIssue, 'assignee' | 'status'>>) => ({ issue }),
    }),

    reducers(() => ({
        tab: [
            IssueTab.Overview as IssueTab,
            {
                setTab: (_, { tab }) => tab,
            },
        ],
        activeEventUUID: [
            undefined as ErrorTrackingEvent['uuid'] | undefined,
            {
                setActiveEventUUID: (_, { uuid }) => uuid,
            },
        ],
    })),

    loaders(({ props, values }) => ({
        issue: [
            null as ErrorTrackingIssue | null,
            {
                loadIssue: async () => {
                    const response = await api.query(
                        errorTrackingIssueQuery({
                            issueId: props.id,
                            dateRange: values.dateRange,
                            filterTestAccounts: values.filterTestAccounts,
                            filterGroup: values.filterGroup,
                        }),
                        {},
                        undefined,
                        true
                    )

                    // ErrorTrackingQuery returns a list of issues
                    // when a fingerprint is supplied there will only be a single issue
                    return response.results[0]
                },
                updateIssue: async ({ issue }) => {
                    const response = await api.errorTracking.updateIssue(props.id, issue)
                    return { ...values.issue, ...response }
                },
                setIssue: ({ issue }) => issue,
            },
        ],
    })),

    selectors({
        breadcrumbs: [
            (s) => [s.issue],
            (issue): Breadcrumb[] => {
                const exceptionType = issue?.name || 'Unknown Type'
                return [
                    {
                        key: Scene.ErrorTracking,
                        name: 'Error tracking',
                        path: urls.errorTracking(),
                    },
                    {
                        key: [Scene.ErrorTrackingIssue, exceptionType],
                        name: exceptionType,
                    },
                ]
            },
        ],

        eventsQuery: [
            (s, p) => [p.id, s.dateRange, s.filterTestAccounts, s.filterGroup],
            (id, dateRange, filterTestAccounts, filterGroup) =>
                errorTrackingIssueEventsQuery({
                    issueId: id,
                    dateRange: dateRange,
                    filterTestAccounts: filterTestAccounts,
                    filterGroup: filterGroup,
                }),
        ],

        issueProperties: [(s) => [s.issue], (issue): Record<string, any> => (issue ? JSON.parse(issue.earliest) : {})],
    }),

    actionToUrl(({ values }) => ({
        setTab: () => {
            const searchParams = router.values.searchParams
            if (values.tab == IssueTab.Overview) {
                delete searchParams['tab']
            } else {
                searchParams['tab'] = values.tab
            }
            return [router.values.location.pathname, searchParams]
        },
    })),

    urlToAction(({ actions }) => ({
        [urls.errorTrackingIssue('*')]: (_, searchParams) => {
            if (searchParams.tab) {
                actions.setTab(searchParams.tab)
            }
        },
    })),
])
