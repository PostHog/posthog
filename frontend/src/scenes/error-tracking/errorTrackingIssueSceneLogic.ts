import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'
import { Breadcrumb } from '~/types'

import type { errorTrackingIssueSceneLogicType } from './errorTrackingIssueSceneLogicType'
import { errorTrackingLogic } from './errorTrackingLogic'
import { errorTrackingIssueEventsQuery, errorTrackingIssueQuery } from './queries'

export interface ErrorTrackingIssueSceneLogicProps {
    id: ErrorTrackingIssue['id']
}

export enum EventsMode {
    Latest = 'latest',
    Earliest = 'earliest',
    Recommended = 'recommended',
    All = 'all',
}

export const errorTrackingIssueSceneLogic = kea<errorTrackingIssueSceneLogicType>([
    path((key) => ['scenes', 'error-tracking', 'errorTrackingIssueSceneLogic', key]),
    props({} as ErrorTrackingIssueSceneLogicProps),
    key((props) => props.id),

    connect({
        values: [errorTrackingLogic, ['dateRange', 'filterTestAccounts', 'filterGroup', 'customSparklineConfig']],
        actions: [errorTrackingLogic, ['setDateRange', 'setFilterTestAccounts', 'setFilterGroup']],
    }),

    actions({
        loadIssue: true,
        setIssue: (issue: ErrorTrackingIssue) => ({ issue }),
        setEventsMode: (mode: EventsMode) => ({ mode }),
        updateIssue: (issue: Partial<Pick<ErrorTrackingIssue, 'assignee' | 'status'>>) => ({ issue }),
    }),

    reducers({
        eventsMode: [
            EventsMode.Latest as EventsMode,
            {
                setEventsMode: (_, { mode }) => mode,
            },
        ],
    }),

    loaders(({ props, values }) => ({
        issue: [
            null as ErrorTrackingIssue | null,
            {
                loadRelationalIssue: async () => {
                    const response = await api.errorTracking.getIssue(props.id)
                    return { ...values.issue, ...response }
                },
                loadClickHouseIssue: async (firstSeen: string, breakpoint) => {
                    breakpoint()
                    const dateRange = {
                        date_from: dayjs(firstSeen).subtract(10, 'day').toISOString(),
                        date_to: values.issue?.last_seen || dayjs().toISOString(),
                    }
                    const response = await api.query(
                        errorTrackingIssueQuery({
                            issueId: props.id,
                            dateRange: dateRange,
                            customVolume: values.customSparklineConfig,
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
            (s) => [s.issue, s.filterTestAccounts, s.filterGroup, s.dateRange],
            (issue, filterTestAccounts, filterGroup, dateRange) =>
                errorTrackingIssueEventsQuery({
                    issue,
                    filterTestAccounts: filterTestAccounts,
                    filterGroup: filterGroup,
                    dateRange,
                }),
        ],

        issueProperties: [
            (s) => [s.issue],
            (issue): Record<string, any> => (issue && issue.earliest ? JSON.parse(issue.earliest) : {}),
        ],
    }),

    listeners(({ values, actions }) => {
        const loadClickHouseIssue = (): void => {
            if (values.issue?.first_seen) {
                actions.loadClickHouseIssue(values.issue.first_seen)
            }
        }

        return {
            loadIssue: () => {
                if (!values.issueLoading) {
                    const issue = values.issue
                    if (!issue) {
                        actions.loadRelationalIssue()
                    } else if (!issue.last_seen) {
                        actions.loadClickHouseIssue(issue.first_seen)
                    }
                }
            },
            setIssueSuccess: () => actions.loadIssue(),
            loadRelationalIssueSuccess: loadClickHouseIssue,
            setDateRange: loadClickHouseIssue,
            setFilterTestAccounts: loadClickHouseIssue,
            setFilterGroup: loadClickHouseIssue,
        }
    }),
])
