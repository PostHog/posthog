import { lemonToast } from '@posthog/lemon-ui'
import { actions, connect, defaults, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { router } from 'kea-router'
import api, { ApiError } from 'lib/api'
import { Dayjs, dayjs } from 'lib/dayjs'
import { posthog } from 'posthog-js'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'
import {
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

type ErrorTrackingIssueStatus = ErrorTrackingIssue['status']

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
        loadAggregations: true,
        setIssue: (issue: ErrorTrackingRelationalIssue) => ({ issue }),
        setSummary: (
            lastSeen: string,
            properties: Record<string, string>,
            aggregations: ErrorTrackingIssueAggregations
        ) => ({ lastSeen, properties, aggregations }),
        updateStatus: (status: ErrorTrackingIssueStatus) => ({ status }),
        updateAssignee: (assignee: ErrorTrackingIssueAssignee | null) => ({ assignee }),
        setIssueLoading: (loading: boolean) => ({ loading }),
        setSummaryLoading: (loading: boolean) => ({ loading }),
    }),

    defaults({
        name: null as string | null,
        description: null as string | null,
        status: null as ErrorTrackingIssueStatus | null,
        assignee: null as ErrorTrackingIssueAssignee | null,
        firstSeen: null as Dayjs | null,
        lastSeen: null as Dayjs | null,
        properties: {} as Record<string, string>,
        aggregations: null as ErrorTrackingIssueAggregations | null,
        issueLoading: false,
        summaryLoading: false,
    }),

    reducers({
        name: {
            setIssue: (_, { issue: { name } }) => name,
        },
        description: {
            setIssue: (_, { issue: { description } }) => description,
        },
        status: {
            setIssue: (_, { issue: { status } }) => status,
            updateStatus: (_, { status }) => status,
        },
        assignee: {
            setIssue: (_, { issue: { assignee } }) => assignee,
            updateAssignee: (_, { assignee }) => assignee,
        },
        firstSeen: {
            setIssue: (_, { issue: { first_seen } }) => dayjs(first_seen),
        },
        lastSeen: {
            setSummary: (_, { lastSeen }) => dayjs(lastSeen),
        },
        properties: {
            setSummary: (_, { properties }) => properties,
        },
        aggregations: {
            setSummary: (_, { aggregations }) => aggregations,
        },
        issueLoading: {
            setIssueLoading: (_, { loading }) => loading,
        },
        summaryLoading: {
            setSummaryLoading: (_, { loading }) => loading,
        },
    }),

    selectors({
        breadcrumbs: [
            (s) => [s.name],
            (name: string | null): Breadcrumb[] => {
                const exceptionType: string = name || 'Unknown Type'
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

        issueDateRange: [
            (s) => [s.firstSeen, s.lastSeen],
            (firstSeen, lastSeen) => {
                if (!firstSeen || !lastSeen) {
                    return null
                }
                return {
                    date_from: firstSeen.startOf('hour').toISOString(),
                    date_to: dayjs().endOf('hour').toISOString(),
                }
            },
        ],
    }),

    listeners(({ props, values, actions }) => {
        function onFailure(error: any, message: string): void {
            posthog.captureException(error)
            lemonToast.error(message)
        }
        const loadAggregations = async (): Promise<void> => {
            try {
                if (!values.firstSeen) {
                    throw new Error('First seen date is required')
                }
                actions.setSummaryLoading(true)
                const response = await api.query(
                    errorTrackingIssueQuery({
                        issueId: props.id,
                        dateRange: {
                            date_from: values.firstSeen.startOf('hour').toISOString(),
                            date_to: dayjs().endOf('hour').toISOString(),
                        },
                        volumeResolution: 40,
                    }),
                    {},
                    undefined,
                    'blocking'
                )
                const issue = response.results[0]
                actions.setSummary(issue.last_seen!, JSON.parse(issue.earliest!), issue.aggregations!)
            } catch (error) {
                onFailure(error, 'Failed to load aggregation metrics')
            } finally {
                actions.setSummaryLoading(false)
            }
        }

        const loadIssue = async (): Promise<void> => {
            try {
                actions.setIssueLoading(true)
                const response = await api.errorTracking.getIssue(props.id, props.fingerprint)
                actions.setIssue(response)
                actions.loadAggregations()
            } catch (error) {
                if (error instanceof ApiError && error.status == 308 && 'issue_id' in error.data) {
                    router.actions.replace(urls.errorTrackingIssue(error.data.issue_id))
                } else {
                    onFailure(error, 'Failed to load issue')
                }
            } finally {
                actions.setIssueLoading(false)
            }
        }

        return {
            loadIssue,
            loadAggregations,
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
