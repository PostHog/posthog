import { lemonToast } from '@posthog/lemon-ui'
import { actions, connect, defaults, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import api from 'lib/api'
import { Dayjs, dayjs } from 'lib/dayjs'
import { posthog } from 'posthog-js'
import { Scene } from 'scenes/sceneTypes'
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

export interface ErrorTrackingIssueSceneLogicProps {
    id: ErrorTrackingIssue['id']
    fingerprint?: string
}

export type ErrorTrackingIssueStatus = ErrorTrackingIssue['status']

export const errorTrackingIssueSceneLogic = kea<errorTrackingIssueSceneLogicType>([
    path((key) => ['scenes', 'error-tracking', 'errorTrackingIssueSceneLogic', key]),
    props({} as ErrorTrackingIssueSceneLogicProps),
    key((props) => props.id),

    connect({
        values: [errorTrackingLogic, ['dateRange', 'filterTestAccounts', 'filterGroup']],
        actions: [errorTrackingLogic, ['setDateRange', 'setFilterTestAccounts', 'setFilterGroup']],
    }),

    actions({
        loadIssue: true,
        loadProperties: (issue: ErrorTrackingRelationalIssue) => ({ issue }),
        loadSummary: (dateRange: DateRange) => ({ dateRange }),
        setIssue: (issue: ErrorTrackingRelationalIssue) => ({ issue }),
        setSummary: (
            lastSeen: string,
            properties: Record<string, string>,
            aggregations: ErrorTrackingIssueAggregations
        ) => ({ lastSeen, properties, aggregations }),
        updateStatus: (status: ErrorTrackingIssueStatus) => ({ status }),
        updateAssignee: (assignee: ErrorTrackingIssueAssignee | null) => ({ assignee }),
    }),

    defaults({
        issue: null as ErrorTrackingRelationalIssue | null,
        properties: {} as Record<string, string>,
        lastSeen: null as Dayjs | null,
        aggregations: null as ErrorTrackingIssueAggregations | null,
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
        lastSeen: {
            setSummary: (_, { lastSeen }) => dayjs(lastSeen),
        },
        aggregations: {
            setSummary: (_, { aggregations }) => aggregations,
        },
    }),

    selectors({
        breadcrumbs: [
            (s) => [s.issue],
            (issue: ErrorTrackingRelationalIssue): Breadcrumb[] => {
                const exceptionType: string = issue.name || 'Unknown Type'
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
            (s) => [(_, props) => props.id, s.filterTestAccounts, s.filterGroup, s.dateRange],
            (issueId, filterTestAccounts, filterGroup, dateRange) =>
                errorTrackingIssueEventsQuery({
                    issueId,
                    filterTestAccounts: filterTestAccounts,
                    filterGroup: filterGroup,
                    dateRange,
                }),
        ],

        issueDateRange: [(s) => [s.issue], (issue) => (issue?.first_seen ? getIssueDateRange(issue) : {})],

        firstSeen: [
            (s) => [s.issue],
            (issue: ErrorTrackingRelationalIssue | null) => (issue?.first_seen ? dayjs(issue.first_seen) : null),
        ],
    }),

    loaders(({ actions, props }) => ({
        issue: {
            loadIssue: async () => {
                const issue = await api.errorTracking.getIssue(props.id, props.fingerprint)
                return issue
            },
        },
        properties: [
            {} as Record<string, string>,
            {
                loadProperties: async ({ issue }) => {
                    const firstSeen = dayjs(issue.first_seen)
                    const response = await api.query(
                        errorTrackingIssueQuery({
                            issueId: props.id,
                            dateRange: {
                                date_from: firstSeen.startOf('minute').toISOString(),
                                date_to: firstSeen.endOf('minute').toISOString(),
                            },
                            volumeResolution: 0,
                        }),
                        {},
                        undefined,
                        'blocking'
                    )
                    const issueAgg = response.results[0]
                    return JSON.parse(issueAgg.earliest!)
                },
            },
        ],
        summary: {
            loadSummary: async ({ dateRange }) => {
                const response = await api.query(
                    errorTrackingIssueQuery({
                        issueId: props.id,
                        dateRange,
                        volumeResolution: 40,
                    }),
                    {},
                    undefined,
                    'blocking'
                )
                const issue = response.results[0]
                actions.setSummary(issue.last_seen!, JSON.parse(issue.earliest!), issue.aggregations!)
                return null
            },
        },
    })),

    listeners(({ props, actions }) => {
        return {
            loadIssueSuccess: [
                ({ issue }) => actions.loadProperties(issue),
                ({ issue }) => actions.loadSummary(getIssueDateRange(issue)),
            ],
            loadIssueFailure: ({ errorObject: { status, data } }) => {
                if (status == 308 && 'issue_id' in data) {
                    router.actions.replace(urls.errorTrackingIssue(data.issue_id))
                } else {
                    lemonToast.error('Failed to load issue')
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
])

function getIssueDateRange(issue: ErrorTrackingRelationalIssue): DateRange {
    return {
        date_from: dayjs(issue.first_seen).startOf('day').toISOString(),
        date_to: dayjs().endOf('minute').toISOString(),
    }
}
