import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import api from 'lib/api'
import { Dayjs, dayjs } from 'lib/dayjs'
import posthog from 'posthog-js'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'
import { ErrorTrackingIssue, ErrorTrackingIssueAssignee } from '~/queries/schema/schema-general'
import { ActivityScope, Breadcrumb } from '~/types'

import type { errorTrackingIssueSceneLogicType } from './errorTrackingIssueSceneLogicType'
import { errorTrackingLogic } from './errorTrackingLogic'
import { errorTrackingIssueEventsQuery, errorTrackingIssueQuery } from './queries'

export interface ErrorTrackingIssueSceneLogicProps {
    id: ErrorTrackingIssue['id']
    fingerprint?: string
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
        initIssue: true,
        setIssue: (issue: ErrorTrackingIssue) => ({ issue }),
        setEventsMode: (mode: EventsMode) => ({ mode }),
        updateIssue: (issue: Partial<Pick<ErrorTrackingIssue, 'status'>>) => ({ issue }),
        assignIssue: (assignee: ErrorTrackingIssueAssignee | null) => ({ assignee }),
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
                    const response = await api.errorTracking.getIssue(props.id, props.fingerprint)
                    return { ...values.issue, ...response }
                },
                loadClickHouseIssue: async (first_seen: Dayjs) => {
                    const hasLastSeen = values.issue && values.issue.last_seen
                    const lastSeen = hasLastSeen ? dayjs(values.issue?.last_seen).endOf('minute') : dayjs()
                    const firstSeen = values.dateRange.date_from
                        ? values.dateRange.date_from
                        : first_seen.startOf('minute').toISOString()

                    const response = await api.query(
                        errorTrackingIssueQuery({
                            issueId: props.id,
                            dateRange: {
                                date_from: firstSeen,
                                date_to: lastSeen.toISOString(),
                            },
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
                    posthog.capture('error_tracking_issue_status_updated', { ...issue, issue_id: props.id })
                    return { ...values.issue, ...response }
                },
                assignIssue: async ({ assignee }) => {
                    await api.errorTracking.assignIssue(props.id, assignee)
                    posthog.capture('error_tracking_issue_assigned', { issue_id: props.id })
                    return values.issue ? { ...values.issue, assignee } : values.issue
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
        const loadIssue = (): void => {
            if (!values.issueLoading) {
                const issue = values.issue
                if (!issue) {
                    actions.loadRelationalIssue()
                } else {
                    actions.loadClickHouseIssue(dayjs(issue.first_seen))
                }
            }
        }

        return {
            setIssueSuccess: loadIssue,
            initIssue: loadIssue,
            loadRelationalIssueSuccess: loadIssue,
            loadRelationalIssueFailure: ({ errorObject: { status, data } }) => {
                if (status == 308 && 'issue_id' in data) {
                    router.actions.replace(urls.errorTrackingIssue(data.issue_id))
                }
            },
            setDateRange: loadIssue,
            setFilterTestAccounts: loadIssue,
            setFilterGroup: loadIssue,
        }
    }),
])
