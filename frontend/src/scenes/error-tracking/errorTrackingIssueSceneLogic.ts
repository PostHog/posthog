import { actions, connect, defaults, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router } from 'kea-router'
import api from 'lib/api'
import { ErrorEventProperties } from 'lib/components/Errors/types'
import { Dayjs, dayjs } from 'lib/dayjs'
import { objectsEqual } from 'lib/utils'
import { posthog } from 'posthog-js'
import { Params, Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'
import {
    DateRange,
    ErrorTrackingIssue,
    ErrorTrackingIssueAggregations,
    ErrorTrackingIssueAssignee,
    ErrorTrackingRelationalIssue,
} from '~/queries/schema/schema-general'
import { ActivityScope, Breadcrumb } from '~/types'

import type { errorTrackingIssueSceneLogicType } from './errorTrackingIssueSceneLogicType'
import { errorTrackingLogic } from './errorTrackingLogic'
import { errorTrackingIssueEventsQuery, errorTrackingIssueQuery } from './queries'
import { defaultSearchParams, resolveDateRange } from './utils'

export interface ErrorTrackingIssueSceneLogicProps {
    id: ErrorTrackingIssue['id']
    fingerprint?: string
}

export type ErrorTrackingIssueStatus = ErrorTrackingIssue['status']

export const errorTrackingIssueSceneLogic = kea<errorTrackingIssueSceneLogicType>([
    path((key) => ['scenes', 'error-tracking', 'errorTrackingIssueSceneLogic', key]),
    props({} as ErrorTrackingIssueSceneLogicProps),
    key((props) => props.id),

    connect(() => ({
        values: [errorTrackingLogic, ['dateRange', 'filterTestAccounts', 'filterGroup', 'searchQuery']],
        actions: [errorTrackingLogic, ['setDateRange', 'setFilterTestAccounts', 'setFilterGroup', 'setSearchQuery']],
    })),

    actions({
        loadIssue: true,
        loadSummary: true,
        loadProperties: (dateRange: DateRange) => ({ dateRange }),
        setIssue: (issue: ErrorTrackingRelationalIssue) => ({ issue }),
        updateStatus: (status: ErrorTrackingIssueStatus) => ({ status }),
        updateAssignee: (assignee: ErrorTrackingIssueAssignee | null) => ({ assignee }),
        setLastSeen: (lastSeen: Dayjs) => ({ lastSeen }),
    }),

    defaults({
        issue: null as ErrorTrackingRelationalIssue | null,
        summary: null as ErrorTrackingIssueSummary | null,
        properties: null as ErrorEventProperties | null,
        volumeResolution: 50,
        lastSeen: null as Dayjs | null,
    }),

    reducers({
        issue: {
            setIssue: (_, { issue }: { issue: ErrorTrackingRelationalIssue }) => issue,
            updateAssignee: (state, { assignee }) => {
                return state ? { ...state, assignee } : null
            },
            updateStatus: (state, { status }) => {
                return state ? { ...state, status } : null
            },
        },
        summary: {},
        volumeResolution: {
            setVolumeResolution: (_, { volumeResolution }: { volumeResolution: number }) => volumeResolution,
        },
        lastSeen: {
            setLastSeen: (prevLastSeen, { lastSeen }) => {
                if (!prevLastSeen || prevLastSeen.isBefore(lastSeen)) {
                    return lastSeen
                }
                return prevLastSeen
            },
        },
    }),

    selectors({
        breadcrumbs: [
            (s) => [s.issue],
            (issue: ErrorTrackingRelationalIssue | null): Breadcrumb[] => {
                const exceptionType: string = issue?.name || 'Issue'
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

        [SIDE_PANEL_CONTEXT_KEY]: [
            (_, p) => [p.id],
            (issueId): SidePanelSceneContext => {
                return {
                    activity_scope: ActivityScope.ERROR_TRACKING_ISSUE,
                    activity_item_id: issueId,
                }
            },
        ],

        eventsQuery: [
            (s) => [(_, props) => props.id, s.filterTestAccounts, s.searchQuery, s.filterGroup, s.dateRange],
            (issueId, filterTestAccounts, searchQuery, filterGroup, dateRange) =>
                errorTrackingIssueEventsQuery({
                    issueId,
                    filterTestAccounts,
                    filterGroup,
                    searchQuery,
                    dateRange: resolveDateRange(dateRange).toDateRange(),
                }),
        ],

        firstSeen: [
            (s) => [s.issue],
            (issue: ErrorTrackingRelationalIssue | null) => (issue ? dayjs(issue.first_seen) : null),
        ],

        aggregations: [(s) => [s.summary], (summary: ErrorTrackingIssueSummary | null) => summary?.aggregations],
    }),

    loaders(({ values, actions, props }) => ({
        issue: {
            loadIssue: async () => await api.errorTracking.getIssue(props.id, props.fingerprint),
        },
        properties: {
            loadProperties: async ({ dateRange }) => {
                // TODO: When properties are loaded for the first time, change stacktrace order to match exception name.
                const response = await api.query(
                    errorTrackingIssueQuery({
                        issueId: props.id,
                        dateRange,
                        filterTestAccounts: false,
                    }),
                    {},
                    undefined,
                    'blocking'
                )
                const issue = response.results[0]
                // Earliest field should be defined as we use the issueId parameter
                return JSON.parse(issue.earliest!)
            },
        },
        summary: {
            loadSummary: async () => {
                const response = await api.query(
                    errorTrackingIssueQuery({
                        issueId: props.id,
                        dateRange: values.dateRange,
                        filterTestAccounts: values.filterTestAccounts,
                        filterGroup: values.filterGroup,
                        searchQuery: values.searchQuery,
                        volumeResolution: values.volumeResolution,
                    }),
                    {},
                    undefined,
                    'blocking'
                )
                if (!response.results.length) {
                    return null
                }
                actions.setLastSeen(dayjs(response.results[0].last_seen))
                const summary = response.results[0]
                return {
                    aggregations: summary.aggregations,
                }
            },
        },
    })),

    listeners(({ props, actions }) => {
        return {
            setDateRange: actions.loadSummary,
            setFilterGroup: actions.loadSummary,
            setFilterTestAccounts: actions.loadSummary,
            setSearchQuery: actions.loadSummary,
            loadIssue: actions.loadSummary,
            loadIssueSuccess: [({ issue }) => actions.loadProperties(getPropertiesDateRange(issue))],
            loadIssueFailure: ({ errorObject: { status, data } }) => {
                if (status == 308 && 'issue_id' in data) {
                    router.actions.replace(urls.errorTrackingIssue(data.issue_id))
                }
            },
            updateStatus: async ({ status }) => {
                posthog.capture('error_tracking_issue_status_updated', { status, issue_id: props.id })
                await api.errorTracking.updateIssue(props.id, { status })
            },
            updateAssignee: async ({ assignee }) => {
                posthog.capture('error_tracking_issue_assigned', { issue_id: props.id })
                await api.errorTracking.assignIssue(props.id, assignee)
            },
        }
    }),

    actionToUrl(({ values }) => {
        const buildURL = (): [
            string,
            Params,
            Record<string, any>,
            {
                replace: boolean
            }
        ] => {
            const searchParams = defaultSearchParams({
                dateRange: values.dateRange,
                searchQuery: values.searchQuery,
                filterGroup: values.filterGroup,
                filterTestAccounts: values.filterTestAccounts,
            })

            if (!objectsEqual(searchParams, router.values.searchParams)) {
                return [router.values.location.pathname, searchParams, router.values.hashParams, { replace: true }]
            }

            return [
                router.values.location.pathname,
                router.values.searchParams,
                router.values.hashParams,
                { replace: false },
            ]
        }

        return {
            setDateRange: () => buildURL(),
            setFilterGroup: () => buildURL(),
            setSearchQuery: () => buildURL(),
            setFilterTestAccounts: () => buildURL(),
        }
    }),
])

function getPropertiesDateRange(issue: ErrorTrackingRelationalIssue): DateRange {
    const firstSeen = dayjs(issue.first_seen)
    return {
        date_from: firstSeen.subtract(1, 'hour').toISOString(),
        date_to: firstSeen.add(1, 'hour').toISOString(),
    }
}

export type ErrorTrackingIssueSummary = {
    aggregations: ErrorTrackingIssueAggregations
}
