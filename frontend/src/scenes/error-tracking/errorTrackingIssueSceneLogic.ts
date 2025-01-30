import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { Dayjs, dayjs } from 'lib/dayjs'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { DateRange, ErrorTrackingIssue } from '~/queries/schema/schema-general'
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

function generateIssueDateRange(first_seen: string, last_seen?: string): DateRange {
    // Minimum 30 days required for Sparkline data
    const thirtyDaysAgo = dayjs().subtract(30, 'day').startOf('day')
    const firstSeen = dayjs(first_seen).startOf('day')

    const thirtyDayMinimum = (date: Dayjs, referenceDate: Dayjs): string => {
        const thirtyDaysPrior = referenceDate.subtract(30, 'day').startOf('day')
        return date.isSameOrAfter(thirtyDaysPrior) ? thirtyDaysPrior.toISOString() : date.startOf('day').toISOString()
    }

    if (last_seen) {
        const lastSeen = dayjs(last_seen).startOf('day')

        if (lastSeen.isBefore(thirtyDaysAgo)) {
            return { date_to: lastSeen.toISOString(), date_from: thirtyDayMinimum(firstSeen, lastSeen) }
        }
        return { date_from: thirtyDaysAgo.toISOString() }
    }
    return { date_from: thirtyDayMinimum(firstSeen, dayjs()) }
}

export const errorTrackingIssueSceneLogic = kea<errorTrackingIssueSceneLogicType>([
    path((key) => ['scenes', 'error-tracking', 'errorTrackingIssueSceneLogic', key]),
    props({} as ErrorTrackingIssueSceneLogicProps),
    key((props) => props.id),

    connect({
        values: [errorTrackingLogic, ['dateRange', 'filterTestAccounts', 'filterGroup']],
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
                    const response = await api.query(
                        errorTrackingIssueQuery({
                            issueId: props.id,
                            dateRange: generateIssueDateRange(firstSeen, values.issue?.last_seen),
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

    listeners(({ values, actions }) => ({
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
        loadRelationalIssueSuccess: ({ issue }) => actions.loadClickHouseIssue(issue.first_seen),
        setIssueSuccess: () => actions.loadIssue(),
    })),
])
