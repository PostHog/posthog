import { actions, connect, defaults, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import api from 'lib/api'
import { ErrorEventProperties, ErrorEventType } from 'lib/components/Errors/types'
import { Dayjs, dayjs } from 'lib/dayjs'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SIDE_PANEL_CONTEXT_KEY, SidePanelSceneContext } from '~/layout/navigation-3000/sidepanel/types'
import {
    DateRange,
    ErrorTrackingIssue,
    ErrorTrackingIssueAggregations,
    ErrorTrackingRelationalIssue,
} from '~/queries/schema/schema-general'
import { ActivityScope, Breadcrumb } from '~/types'

import { errorFiltersLogic } from './components/ErrorFilters/errorFiltersLogic'
import { issueActionsLogic } from './components/IssueActions/issueActionsLogic'
import type { errorTrackingIssueSceneLogicType } from './errorTrackingIssueSceneLogicType'
import { errorTrackingIssueQuery } from './queries'
import { ERROR_TRACKING_DETAILS_RESOLUTION } from './utils'

export interface ErrorTrackingIssueSceneLogicProps {
    id: ErrorTrackingIssue['id']
    fingerprint?: string
}

export type ErrorTrackingIssueStatus = ErrorTrackingIssue['status']

export const errorTrackingIssueSceneLogic = kea<errorTrackingIssueSceneLogicType>([
    path((key) => ['scenes', 'error-tracking', 'errorTrackingIssueSceneLogic', key]),
    props({} as ErrorTrackingIssueSceneLogicProps),
    key((props) => props.id),

    connect(() => {
        const filtersLogic = errorFiltersLogic()
        const issueActions = issueActionsLogic()
        return {
            values: [filtersLogic, ['dateRange', 'filterTestAccounts', 'filterGroup', 'searchQuery']],
            actions: [
                filtersLogic,
                ['setDateRange', 'setFilterTestAccounts', 'setFilterGroup', 'setSearchQuery'],
                issueActions,
                ['updateIssueAssignee', 'updateIssueStatus', 'updateIssueName'],
            ],
        }
    }),

    actions({
        loadIssue: true,
        loadSummary: true,
        loadFirstSeenEvent: (timestamp: string) => ({ timestamp }),
        setIssue: (issue: ErrorTrackingRelationalIssue) => ({ issue }),
        setLastSeen: (lastSeen: Dayjs) => ({ lastSeen }),
        selectEvent: (event: ErrorEventType | null) => ({
            event,
        }),
    }),

    defaults({
        issue: null as ErrorTrackingRelationalIssue | null,
        summary: null as ErrorTrackingIssueSummary | null,
        properties: null as ErrorEventProperties | null,
        lastSeen: null as Dayjs | null,
        firstSeenEvent: null as ErrorEventType | null,
        selectedEvent: null as ErrorEventType | null,
    }),

    reducers(({ values }) => ({
        issue: {
            setIssue: (_, { issue }: { issue: ErrorTrackingRelationalIssue }) => issue,
            updateIssueAssignee: (state, { id, assignee }) => {
                if (state && id == state.id) {
                    return { ...state, assignee }
                }
                return state
            },
            updateIssueStatus: (state, { id, status }) => {
                if (state && id == state.id) {
                    return { ...state, status }
                }
                return state
            },
            updateIssueName: (state, { name }) => {
                return state ? { ...state, name } : null
            },
        },
        summary: {},
        lastSeen: {
            setLastSeen: (prevLastSeen, { lastSeen }) => {
                if (!prevLastSeen || prevLastSeen.isBefore(lastSeen)) {
                    return lastSeen
                }
                return prevLastSeen
            },
        },
        selectedEvent: {
            selectEvent: (_, { event }) => {
                if (!event && values.firstSeenEvent) {
                    return values.firstSeenEvent
                }
                return event
            },
        },
    })),

    loaders(({ values, actions, props }) => ({
        issue: {
            loadIssue: async () => await api.errorTracking.getIssue(props.id, props.fingerprint),
        },
        firstSeenEvent: {
            loadFirstSeenEvent: async ({ timestamp }) => {
                const response = await api.query(
                    errorTrackingIssueQuery({
                        issueId: props.id,
                        dateRange: getNarrowDateRange(timestamp),
                        filterTestAccounts: false,
                        withAggregations: false,
                        withFirstEvent: true,
                    }),
                    {},
                    undefined,
                    'blocking'
                )
                const issue = response.results[0]
                if (!issue.first_event) {
                    return null
                }
                const first_event_properties = JSON.parse(issue.first_event.properties)
                const firstSeenEvent: ErrorEventType = {
                    uuid: issue.first_event.uuid,
                    timestamp: issue.first_event.timestamp,
                    person: { distinct_ids: [], properties: {} },
                    properties: first_event_properties,
                }
                if (!values.selectedEvent) {
                    actions.selectEvent(firstSeenEvent)
                }
                return firstSeenEvent
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
                        volumeResolution: ERROR_TRACKING_DETAILS_RESOLUTION,
                        withAggregations: true,
                        withFirstEvent: false,
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
                if (!summary.aggregations) {
                    return null
                }
                return {
                    aggregations: summary.aggregations,
                }
            },
        },
    })),

    selectors(({ asyncActions, props }) => ({
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
                        onRename: async (name: string) => {
                            return await asyncActions.updateIssueName({ id: props.id, name })
                        },
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
        issueId: [(_, p) => [p.id], (id: string) => id],
        firstSeen: [
            (s) => [s.issue],
            (issue: ErrorTrackingRelationalIssue | null) => (issue ? dayjs(issue.first_seen) : null),
        ],

        aggregations: [(s) => [s.summary], (summary: ErrorTrackingIssueSummary | null) => summary?.aggregations],
    })),

    listeners(({ actions }) => {
        return {
            setDateRange: actions.loadSummary,
            setFilterGroup: actions.loadSummary,
            setFilterTestAccounts: actions.loadSummary,
            setSearchQuery: actions.loadSummary,
            loadIssue: actions.loadSummary,
            loadIssueSuccess: [({ issue }) => actions.loadFirstSeenEvent(issue.first_seen)],
            loadIssueFailure: ({ errorObject: { status, data } }) => {
                if (status == 308 && 'issue_id' in data) {
                    router.actions.replace(urls.errorTrackingIssue(data.issue_id))
                }
            },
        }
    }),
])

function getNarrowDateRange(timestamp: Dayjs | string): DateRange {
    const firstSeen = dayjs(timestamp)
    return {
        date_from: firstSeen.subtract(1, 'hour').toISOString(),
        date_to: firstSeen.add(1, 'hour').toISOString(),
    }
}

export type ErrorTrackingIssueSummary = {
    aggregations: ErrorTrackingIssueAggregations
}
