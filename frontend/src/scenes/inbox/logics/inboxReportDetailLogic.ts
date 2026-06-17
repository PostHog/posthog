import { actions, afterMount, kea, key, listeners, path, props, propsChanged, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api, { PaginatedResponse } from 'lib/api'
import { SignalNode } from 'scenes/debug/signals/types'
import { userLogic } from 'scenes/userLogic'

import { Task, TaskRunStatus } from 'products/tasks/frontend/types'

import {
    AvailableReviewerOption,
    buildAddReviewerOptions,
    CurrentReviewerUser,
} from '../components/detail/reviewerDisplay'
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

/** Run statuses that count as terminal. Mirrors desktop `isTerminalStatus` / `ReportTasksSection`. */
const TERMINAL_RUN_STATUSES: TaskRunStatus[] = [TaskRunStatus.COMPLETED, TaskRunStatus.FAILED, TaskRunStatus.CANCELLED]

export interface InboxReportDetailLogicProps {
    reportId: string
    /** The selected report, fed in by the shell so task polling can stop once it reaches a terminal status. */
    report?: SignalReport | null
}

/** A linked task plus the relationship and when the link was created. Mirrors desktop `ReportTaskData`. */
export interface ReportTaskEntry {
    task: Task
    relationship: SignalReportTaskRelationship
    startedAt: string
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
        // Optimistically replace the reviewer list while the PUT is in flight, then reload from the server.
        // Mirrors desktop `useUpdateSuggestedReviewers` optimistic behavior.
        updateReviewers: (artefactId: string, content: Record<string, string>[], optimistic: EnrichedReviewer[]) => ({
            artefactId,
            content,
            optimistic,
        }),
        setOptimisticReviewers: (reviewers: EnrichedReviewer[] | null) => ({ reviewers }),
        // Debounced server-side org-member search for the add-reviewer picker.
        searchAvailableReviewers: (query: string) => ({ query }),
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
                // Org members with a linked GitHub identity who can be added as reviewers.
                // Filtered server-side via `query` (the backend ranks + caps at 100) so the picker
                // isn't limited to the alphabetical first page. Empty query loads the default page.
                loadAvailableReviewers: async ({ query }: { query?: string } = {}) => {
                    return await api.signalReports.availableReviewers(query)
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
        // While a reviewer update is in flight, this overrides the artefact-derived list so the UI
        // reflects the change immediately. Cleared once the reload lands (or the update fails).
        optimisticReviewers: [
            null as EnrichedReviewer[] | null,
            {
                updateReviewers: (_, { optimistic }) => optimistic,
                setOptimisticReviewers: (_, { reviewers }) => reviewers,
            },
        ],
    }),

    selectors({
        // Mirrors the optimistic override lifecycle: an update is in flight exactly while the
        // optimistic list is set (cleared once the reload lands or the update fails).
        isUpdatingReviewers: [(s) => [s.optimisticReviewers], (optimisticReviewers) => optimisticReviewers !== null],
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
        // The reviewer list to render: optimistic override (if any) wins over the artefact-derived list,
        // then the current user is pinned to the top. Mirrors desktop `displayReviewers`.
        displayReviewers: [
            (s) => [s.reportReviewers, s.optimisticReviewers, userLogic.selectors.user],
            (
                reportReviewers: EnrichedReviewer[] | null,
                optimisticReviewers: EnrichedReviewer[] | null,
                user: { uuid: string } | null
            ): EnrichedReviewer[] | null => {
                const reviewers = optimisticReviewers ?? reportReviewers
                if (!reviewers) {
                    return null
                }
                const meUuid = user?.uuid
                if (!meUuid) {
                    return reviewers
                }
                const meIndex = reviewers.findIndex((r) => r.user?.uuid === meUuid)
                if (meIndex <= 0) {
                    return reviewers
                }
                return [reviewers[meIndex], ...reviewers.filter((_, i) => i !== meIndex)]
            },
        ],
        // Add-reviewer options: org members with GitHub, current user pinned first ("Me"). Mirrors desktop.
        addReviewerOptions: [
            (s) => [s.availableReviewers, userLogic.selectors.user],
            (
                availableReviewers: AvailableReviewerOption[] | null,
                currentUser: { uuid: string; first_name?: string; last_name?: string; email?: string } | null
            ): AvailableReviewerOption[] => {
                const me: CurrentReviewerUser | null = currentUser
                    ? {
                          uuid: currentUser.uuid,
                          first_name: currentUser.first_name,
                          last_name: currentUser.last_name,
                          email: currentUser.email,
                      }
                    : null
                return buildAddReviewerOptions(availableReviewers ?? [], me)
            },
        ],
        // True when a re-research is under way: ≥2 research tasks, one currently in-flight while a prior
        // attempt already reached a terminal state. Mirrors desktop `AgentRunDetail`'s `isReResearch`.
        isReResearch: [
            (s) => [s.reportTasks],
            (reportTasks: ReportTaskEntry[] | null): boolean => {
                if (!reportTasks) {
                    return false
                }
                const researchTasks = reportTasks.filter((rt) => rt.relationship === 'research')
                if (researchTasks.length < 2) {
                    return false
                }
                const hasInFlight = researchTasks.some((rt) => {
                    const status = rt.task.latest_run?.status
                    return !!status && !TERMINAL_RUN_STATUSES.includes(status)
                })
                const hasPriorTerminal = researchTasks.some((rt) => {
                    const status = rt.task.latest_run?.status
                    return !!status && TERMINAL_RUN_STATUSES.includes(status)
                })
                return hasInFlight && hasPriorTerminal
            },
        ],
    }),

    listeners(({ actions, values, cache, props }) => ({
        searchAvailableReviewers: async ({ query }, breakpoint) => {
            await breakpoint(300)
            actions.loadAvailableReviewers({ query: query.trim() || undefined })
        },
        // Persist a reviewer add/remove. The optimistic list is already in place (set by the action's
        // reducer); on success reload the artefact so we converge on the server's enriched data, and on
        // failure clear the optimistic override so the UI snaps back. Mirrors desktop `useUpdateSuggestedReviewers`.
        updateReviewers: async ({ artefactId, content }) => {
            try {
                await api.signalReports.updateArtefact(props.reportId, artefactId, content)
                await actions.loadReportArtefacts()
            } catch (error: any) {
                lemonToast.error(error?.detail || error?.message || 'Failed to update reviewers')
            } finally {
                // Clear the optimistic override; the freshly-loaded artefact is now the source of truth.
                actions.setOptimisticReviewers(null)
            }
        },
        // Poll linked tasks only while the report is active; stop once it reaches a terminal status
        // (or is unloaded). Mirrors desktop `useReportTasks` gating. The keyed disposable replaces
        // any running interval on re-add and is torn down automatically on unmount / tab hide.
        setReport: () => {
            if (values.isReportActive) {
                cache.disposables.add(() => {
                    const interval = setInterval(() => actions.loadReportTasks(), REPORT_TASKS_POLL_INTERVAL_MS)
                    return () => clearInterval(interval)
                }, 'reportTasksPoll')
            } else {
                cache.disposables.dispose('reportTasksPoll')
            }
        },
    })),

    propsChanged(({ actions, props }, oldProps) => {
        // The shell re-renders the detail with a refreshed `selectedReport`; re-gate polling on the new status.
        if (props.report !== oldProps.report) {
            actions.setReport(props.report ?? null)
        }
    }),

    afterMount(({ actions, props }) => {
        actions.loadReportArtefacts()
        actions.loadReportSignals()
        actions.loadReportTasks()
        actions.loadAvailableReviewers()
        // Seed the report from props so polling is gated on its status from the first tick.
        actions.setReport(props.report ?? null)
    }),
])
