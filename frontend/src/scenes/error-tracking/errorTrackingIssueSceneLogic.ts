import { actions, connect, defaults, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import api from 'lib/api'
import { stackFrameLogic } from 'lib/components/Errors/stackFrameLogic'
import { ErrorTrackingException } from 'lib/components/Errors/types'
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
import {
    ExceptionAttributes,
    getExceptionAttributes,
    getSessionId,
    hasNonInAppFrames,
    hasStacktrace,
    resolveDateRange,
} from './utils'

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
        values: [
            errorTrackingLogic,
            ['dateRange', 'filterTestAccounts', 'filterGroup', 'showStacktrace', 'showContext', 'searchQuery'],
            stackFrameLogic,
            ['frameOrderReversed', 'showAllFrames', 'showFingerprint'],
        ],
        actions: [
            errorTrackingLogic,
            [
                'setDateRange',
                'setFilterTestAccounts',
                'setFilterGroup',
                'setShowStacktrace',
                'setShowContext',
                'setSearchQuery',
            ],
            stackFrameLogic,
            ['setFrameOrderReversed', 'setShowAllFrames', 'setShowFingerprint'],
        ],
    }),

    actions({
        loadIssue: true,
        loadSummary: true,
        loadProperties: (dateRange: DateRange) => ({ dateRange }),
        setIssue: (issue: ErrorTrackingRelationalIssue) => ({ issue }),
        updateStatus: (status: ErrorTrackingIssueStatus) => ({ status }),
        updateAssignee: (assignee: ErrorTrackingIssueAssignee | null) => ({ assignee }),
        setVolumeResolution: (volumeResolution: number) => ({ volumeResolution }),
    }),

    defaults({
        issue: null as ErrorTrackingRelationalIssue | null,
        properties: {} as Record<string, string>,
        summary: null as ErrorTrackingIssueSummary | null,
        volumeResolution: 50,
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
        properties: {},
        volumeResolution: {
            setVolumeResolution: (_, { volumeResolution }: { volumeResolution: number }) => volumeResolution,
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
            (s) => [(_, props) => props.id, s.filterTestAccounts, s.filterGroup, s.dateRange],
            (issueId, filterTestAccounts, filterGroup, dateRange) =>
                errorTrackingIssueEventsQuery({
                    issueId,
                    filterTestAccounts: filterTestAccounts,
                    filterGroup: filterGroup,
                    dateRange: resolveDateRange(dateRange).toDateRange(),
                }),
        ],

        firstSeen: [
            (s) => [s.issue],
            (issue: ErrorTrackingRelationalIssue | null) => (issue ? dayjs(issue.first_seen) : null),
        ],

        aggregations: [(s) => [s.summary], (summary: ErrorTrackingIssueSummary | null) => summary?.aggregations],
        exceptionAttributes: [
            (s) => [s.properties],
            (properties: Record<string, string>) => (properties ? getExceptionAttributes(properties) : null),
        ],
        exceptionList: [
            (s) => [s.exceptionAttributes, s.frameOrderReversed],
            (attributes: ExceptionAttributes | null, orderReversed: boolean) => {
                if (!attributes || !attributes.exceptionList) {
                    return []
                }
                return applyFrameOrder(attributes.exceptionList, orderReversed)
            },
        ],
        fingerprintRecords: [
            (s) => [s.exceptionAttributes],
            (attributes: ExceptionAttributes | null) => attributes?.fingerprintRecords,
        ],
        hasNonInAppFrames: [
            (s) => [s.exceptionList],
            (excList: ErrorTrackingException[]) => hasNonInAppFrames(excList),
        ],
        hasStacktrace: [(s) => [s.exceptionList], (excList: ErrorTrackingException[]) => hasStacktrace(excList)],
        sessionId: [
            (s) => [s.properties],
            (properties: Record<string, string> | null) => (properties ? getSessionId(properties) : undefined),
        ],
    }),

    loaders(({ values, props }) => ({
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
                        volumeResolution: 0,
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
        lastSeen: {
            loadLastSeen: async () => {
                // TODO: Load last seen from API
                return dayjs()
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
                const summary = response.results[0]
                return {
                    aggregations: summary.aggregations,
                } as ErrorTrackingIssueSummary
            },
        },
    })),

    listeners(({ props, actions }) => {
        return {
            setDateRange: actions.loadSummary,
            setFilterGroup: actions.loadSummary,
            setFilterTestAccounts: actions.loadSummary,
            setSearchQuery: actions.loadSummary,
            loadIssue: [actions.loadSummary, actions.loadLastSeen],
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
])

function getPropertiesDateRange(issue: ErrorTrackingRelationalIssue): DateRange {
    const firstSeen = dayjs(issue.first_seen)
    return {
        date_from: firstSeen.startOf('minute').toISOString(),
        date_to: firstSeen.endOf('minute').toISOString(),
    }
}

function applyFrameOrder(
    exceptionList: ErrorTrackingException[],
    frameOrderReversed: boolean
): ErrorTrackingException[] {
    if (frameOrderReversed) {
        return exceptionList
            .map((exception) => {
                const copiedException = { ...exception }
                if (copiedException.stacktrace) {
                    copiedException.stacktrace = {
                        ...copiedException.stacktrace,
                        frames: copiedException.stacktrace.frames.slice().reverse(),
                    }
                }
                return copiedException
            })
            .reverse()
    }
    return [...exceptionList]
}

export type ErrorTrackingIssueSummary = {
    lastSeen: Dayjs
    aggregations: ErrorTrackingIssueAggregations
}
