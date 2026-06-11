import { actions, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api, { PaginatedResponse } from 'lib/api'
import { SignalNode } from 'scenes/debug/signals/types'

import { Task } from 'products/tasks/frontend/types'

import {
    EnrichedReviewer,
    SignalReport,
    SignalReportArtefact,
    SignalReportArtefactResponse,
    SignalReportStatus,
    SignalReportTask,
    SignalReportTaskRelationship,
} from '../types'
import type { inboxReportDetailLogicType } from './inboxReportDetailLogicType'

export interface InboxReportDetailLogicProps {
    reportId: string
}

/** A linked task plus the relationship and when the link was created. Mirrors desktop `ReportTaskData`. */
export interface ReportTaskEntry {
    task: Task
    relationship: SignalReportTaskRelationship
    startedAt: string
}

export interface AvailableReviewerOption {
    user_uuid: string
    name: string
    email: string
}

// Only these relationships are rendered, implementation-first. Mirrors desktop `useReportTasks`.
const DISPLAYED_RELATIONSHIPS: SignalReportTaskRelationship[] = ['implementation', 'research']

// While the report is still being worked, poll linked tasks every 5s. Mirrors desktop.
const ACTIVE_STATUSES: SignalReportStatus[] = [
    SignalReportStatus.CANDIDATE,
    SignalReportStatus.IN_PROGRESS,
    SignalReportStatus.PENDING_INPUT,
]

const REPORT_TASKS_POLL_INTERVAL_MS = 5000

/** Extract the PR url from a task's latest run output, if present. Mirrors desktop `getTaskPrUrl`. */
export function getTaskPrUrl(task: Task): string | null {
    const prUrl = task.latest_run?.output?.pr_url
    return typeof prUrl === 'string' && prUrl.length > 0 ? prUrl : null
}

/**
 * Per-selected-report detail logic: artefacts, contributing signals, suggested reviewers, and linked tasks.
 * Keyed by `reportId` so each open report gets its own mounted instance. Does NOT import `inboxSceneLogic`
 * (the report id is passed in as a prop) to avoid a logic cycle.
 */
export const inboxReportDetailLogic = kea<inboxReportDetailLogicType>([
    path(['scenes', 'inbox', 'logics', 'inboxReportDetailLogic']),
    props({} as InboxReportDetailLogicProps),
    key((props) => props.reportId),

    actions({
        setReport: (report: SignalReport | null) => ({ report }),
    }),

    loaders(({ props }) => ({
        reportArtefacts: [
            null as SignalReportArtefact[] | null,
            {
                loadReportArtefacts: async () => {
                    const response: SignalReportArtefactResponse = await api.signalReports.artefacts(props.reportId)
                    return response.results
                },
            },
        ],
        reportSignals: [
            null as SignalNode[] | null,
            {
                loadReportSignals: async () => {
                    const response = await api.signalReports.getReportSignals(props.reportId)
                    return response.signals
                },
            },
        ],
        reportTasks: [
            null as ReportTaskEntry[] | null,
            {
                loadReportTasks: async () => {
                    const response: PaginatedResponse<SignalReportTask> = await api.signalReports.tasks(props.reportId)
                    const relevant = response.results.filter((rt) => DISPLAYED_RELATIONSHIPS.includes(rt.relationship))
                    const entries = await Promise.all(
                        relevant.map(async (rt): Promise<ReportTaskEntry> => {
                            const task = await api.tasks.get(rt.task_id)
                            return { task, relationship: rt.relationship, startedAt: rt.created_at }
                        })
                    )
                    return entries.sort(
                        (a, b) =>
                            DISPLAYED_RELATIONSHIPS.indexOf(a.relationship) -
                            DISPLAYED_RELATIONSHIPS.indexOf(b.relationship)
                    )
                },
            },
        ],
        availableReviewers: [
            null as AvailableReviewerOption[] | null,
            {
                loadAvailableReviewers: async (query?: string) => {
                    const response = await api.signalReports.availableReviewers(query)
                    return response.results
                },
            },
        ],
    })),

    reducers({
        report: [
            null as SignalReport | null,
            {
                setReport: (_, { report }) => report,
            },
        ],
    }),

    selectors({
        reportReviewers: [
            (s) => [s.reportArtefacts],
            (reportArtefacts: SignalReportArtefact[] | null): EnrichedReviewer[] | null => {
                if (!reportArtefacts) {
                    return null
                }
                const reviewersArtefact = reportArtefacts.find((a) => a.type === 'suggested_reviewers')
                if (!reviewersArtefact) {
                    return null
                }
                return reviewersArtefact.content as unknown as EnrichedReviewer[]
            },
        ],
        isReportActive: [
            (s) => [s.report],
            (report: SignalReport | null): boolean => (report ? ACTIVE_STATUSES.includes(report.status) : false),
        ],
    }),

    listeners(({ actions, values, cache }) => ({
        // Once the shell feeds in the report (via `setReport`), poll linked tasks only while it's
        // active; stop once it reaches a terminal status. Mirrors desktop `useReportTasks` gating.
        setReport: () => {
            clearInterval(cache.reportTasksPollInterval)
            if (values.report === null || values.isReportActive) {
                cache.reportTasksPollInterval = setInterval(() => {
                    actions.loadReportTasks()
                }, REPORT_TASKS_POLL_INTERVAL_MS)
            }
        },
    })),

    events(({ actions, cache }) => ({
        afterMount: () => {
            actions.loadReportArtefacts()
            actions.loadReportSignals()
            actions.loadReportTasks()
            // Poll until the shell tells us the report is terminal. Until `setReport` is called we
            // don't know the status, so default to polling so in-flight runs still refresh.
            clearInterval(cache.reportTasksPollInterval)
            cache.reportTasksPollInterval = setInterval(() => {
                actions.loadReportTasks()
            }, REPORT_TASKS_POLL_INTERVAL_MS)
        },
        beforeUnmount: () => {
            clearInterval(cache.reportTasksPollInterval)
        },
    })),
])
