import { actions, afterMount, kea, key, listeners, path, props, propsChanged, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { SignalNode } from 'scenes/debug/signals/types'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { Task, TaskRunStatus } from 'products/posthog_ai/frontend/types/taskTypes'
import {
    signalsReportArtefactsDiff,
    signalsReportArtefactsReviewComments,
} from 'products/signals/frontend/generated/api'
import type { CommitDiffResponseApi, ReviewCommentsResponseApi } from 'products/signals/frontend/generated/api.schemas'

import {
    deriveTaskPurpose,
    PURPOSE_ORDER,
    ReportTaskPurpose,
    TaskRunArtefactContent,
} from '../components/detail/artefactTypes'
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
} from '../types'
import type { inboxReportDetailLogicType } from './inboxReportDetailLogicType'

/** Run statuses that count as terminal. Mirrors desktop `isTerminalStatus` / `ReportTasksSection`. */
const TERMINAL_RUN_STATUSES: TaskRunStatus[] = [TaskRunStatus.COMPLETED, TaskRunStatus.FAILED, TaskRunStatus.CANCELLED]

// The task↔report association is the `task_run` artefact log now (the legacy `/tasks/` endpoint is
// gone), and the activity timeline renders the whole log. Pull a generous page so early entries
// (the first task runs, repo selection) stay visible on reports with many findings — matching the
// limit the kickoff flow already uses to find the repo-selection artefact.
const ARTEFACT_FETCH_LIMIT = 1000

export interface InboxReportDetailLogicProps {
    reportId: string
    /** The selected report, fed in by the shell so task polling can stop once it reaches a terminal status. */
    report?: SignalReport | null
}

/** A linked task plus its derived purpose and when the association was first recorded. Mirrors desktop `ReportTaskData`. */
export interface ReportTaskEntry {
    task: Task
    purpose: ReportTaskPurpose
    purposeLabel: string
    startedAt: string
}

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
 * `explanation` text from the latest judgment artefact of `type`, or null. The priority/actionability
 * judgment artefacts already carry the agent's rationale — surfaced in the detail view without any extra fetch.
 */
function latestJudgmentExplanation(
    artefacts: SignalReportArtefact[] | null,
    type: 'priority_judgment' | 'actionability_judgment'
): string | null {
    const matching = (artefacts ?? []).filter((a) => a.type === type)
    if (matching.length === 0) {
        return null
    }
    const latest = matching.reduce((a, b) => (b.created_at > a.created_at ? b : a))
    const explanation = latest.content?.explanation
    return typeof explanation === 'string' && explanation.trim() ? explanation : null
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
        // Which linked task's run log the detail view shows; null falls back to `primaryTask`.
        setSelectedTaskId: (taskId: string | null) => ({ taskId }),
        // Inline-expand a linked task's run log within the report detail's Runs section.
        toggleExpandedTask: (taskId: string) => ({ taskId }),
    }),

    loaders(({ props, values }) => ({
        reportArtefacts: [
            null as SignalReportArtefact[] | null,
            {
                loadReportArtefacts: async () => {
                    const response: SignalReportArtefactResponse = await api.signalReports.artefacts(props.reportId, {
                        limit: ARTEFACT_FETCH_LIMIT,
                    })
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
                // The task↔report association lives in the `task_run` artefact log: each artefact's
                // `(product, type)` derives the task's purpose. We group by task id (earliest
                // association wins for `startedAt`), drop `repo_selection` (pipeline plumbing), then
                // resolve each task. Mirrors desktop `useReportTasks`. Derives from the already-loaded
                // `reportArtefacts` (re-run after each artefact load) rather than re-fetching them.
                loadReportTasks: async () => {
                    const artefacts = values.reportArtefacts ?? []
                    const associations = new Map<
                        string,
                        { purpose: ReportTaskPurpose; purposeLabel: string; startedAt: string }
                    >()
                    for (const artefact of artefacts) {
                        if (artefact.type !== 'task_run') {
                            continue
                        }
                        const content = artefact.content as TaskRunArtefactContent
                        if (!content?.task_id) {
                            continue
                        }
                        const derived = deriveTaskPurpose(content)
                        if (!derived) {
                            continue
                        }
                        const existing = associations.get(content.task_id)
                        if (!existing) {
                            associations.set(content.task_id, { ...derived, startedAt: artefact.created_at })
                        } else if (artefact.created_at < existing.startedAt) {
                            // Keep the earliest association's timestamp + purpose for this task.
                            associations.set(content.task_id, { ...derived, startedAt: artefact.created_at })
                        }
                    }
                    const entries = await Promise.all(
                        [...associations.entries()].map(async ([taskId, meta]): Promise<ReportTaskEntry | null> => {
                            try {
                                const task = await api.tasks.get(taskId)
                                return { task, ...meta }
                            } catch {
                                // A deleted/inaccessible task drops out of the list rather than failing the load.
                                return null
                            }
                        })
                    )
                    return entries
                        .filter((entry): entry is ReportTaskEntry => entry !== null)
                        .sort(
                            (a, b) =>
                                PURPOSE_ORDER.indexOf(a.purpose) - PURPOSE_ORDER.indexOf(b.purpose) ||
                                new Date(a.startedAt).getTime() - new Date(b.startedAt).getTime()
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
        // The report's branch diff (its `commit` artefact's branch vs the repo default branch), rendered
        // in the "Files changed" section. Loaded here rather than in the component so the fetch is keyed
        // to the report and cascades off the artefact load — once artefacts resolve we know the latest
        // commit artefact, and re-fetch only when a *new* commit lands (not on every 5s activity poll).
        reportDiff: [
            null as CommitDiffResponseApi | null,
            {
                loadReportDiff: async ({ artefactId }: { artefactId: string }) => {
                    const teamId = teamLogic.values.currentTeamId
                    if (!teamId) {
                        return null
                    }
                    return await signalsReportArtefactsDiff(String(teamId), props.reportId, artefactId)
                },
            },
        ],
        // The review conversation on the report's implementation PR (submitted reviews, inline diff
        // comments, and conversation comments), rendered in the "Review comments" section. Loaded here
        // rather than in the component so it's keyed to the report and cascades off the artefact load —
        // it hangs off the latest commit artefact and re-fetches only when a *new* commit lands, matching
        // `reportDiff`.
        reportReviewComments: [
            null as ReviewCommentsResponseApi | null,
            {
                loadReportReviewComments: async ({ artefactId }: { artefactId: string }) => {
                    const teamId = teamLogic.values.currentTeamId
                    if (!teamId) {
                        return null
                    }
                    return await signalsReportArtefactsReviewComments(String(teamId), props.reportId, artefactId)
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
        // Explicit task selection for the run-log viewer. Reset when the report changes so a freshly
        // opened run starts on its `primaryTask`.
        selectedTaskId: [
            null as string | null,
            {
                setSelectedTaskId: (_, { taskId }) => taskId,
                setReport: () => null,
            },
        ],
        // Linked tasks whose run log is expanded inline in the Runs section. Reset when the report
        // changes so a freshly opened report starts with everything collapsed.
        expandedTaskIds: [
            [] as string[],
            {
                toggleExpandedTask: (state, { taskId }) =>
                    state.includes(taskId) ? state.filter((id) => id !== taskId) : [...state, taskId],
                setReport: () => [],
            },
        ],
        // Human-readable diff-load failure (kea-loaders only exposes a boolean loading flag). A failed
        // compare usually means the branch was merged, deleted, or force-rewritten away.
        reportDiffError: [
            null as string | null,
            {
                loadReportDiff: () => null,
                loadReportDiffSuccess: () => null,
                loadReportDiffFailure: () =>
                    "Couldn't load the diff — the branch may have been merged, deleted, or rewritten.",
            },
        ],
        // The commit artefact the current `reportDiff` was loaded for, so the artefact poll re-fetches
        // the diff only when a new commit lands rather than on every tick.
        diffArtefactId: [
            null as string | null,
            {
                loadReportDiff: (_, { artefactId }) => artefactId,
            },
        ],
        // Human-readable review-comments-load failure (kea-loaders only exposes a boolean loading flag).
        // A failure usually means the PR could not be resolved or GitHub was unreachable.
        reportReviewCommentsError: [
            null as string | null,
            {
                loadReportReviewComments: () => null,
                loadReportReviewCommentsSuccess: () => null,
                loadReportReviewCommentsFailure: () =>
                    "Couldn't load review comments. The pull request may have been closed, or GitHub was unreachable.",
            },
        ],
        // The commit artefact the current `reportReviewComments` was loaded for, so the artefact poll
        // re-fetches only when a new commit lands rather than on every tick.
        reviewCommentsArtefactId: [
            null as string | null,
            {
                loadReportReviewComments: (_, { artefactId }) => artefactId,
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
        // The most recent `commit` artefact — its branch is treated as the report's branch to diff
        // against the repository default branch. A report's code work may span several pushes; the
        // latest commit's branch tip is the current state worth inspecting.
        latestCommitArtefact: [
            (s) => [s.reportArtefacts],
            (reportArtefacts: SignalReportArtefact[] | null): SignalReportArtefact | null => {
                const commits = (reportArtefacts ?? []).filter((a) => a.type === 'commit')
                if (commits.length === 0) {
                    return null
                }
                return commits.reduce((latest, a) => (a.created_at > latest.created_at ? a : latest))
            },
        ],
        // Rationale behind the priority / actionability judgments, pulled from the already-loaded artefacts.
        priorityExplanation: [
            (s) => [s.reportArtefacts],
            (reportArtefacts: SignalReportArtefact[] | null): string | null =>
                latestJudgmentExplanation(reportArtefacts, 'priority_judgment'),
        ],
        actionabilityExplanation: [
            (s) => [s.reportArtefacts],
            (reportArtefacts: SignalReportArtefact[] | null): string | null =>
                latestJudgmentExplanation(reportArtefacts, 'actionability_judgment'),
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
                const researchTasks = reportTasks.filter((rt) => rt.purpose === 'research')
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
        // The default task whose run log is shown: prefer one still in motion, tie-break by most-recent
        // link. Mirrors desktop `AgentRunDetail`'s `pickPrimaryTask`.
        primaryTask: [
            (s) => [s.reportTasks],
            (reportTasks: ReportTaskEntry[] | null): ReportTaskEntry | null => {
                if (!reportTasks || reportTasks.length === 0) {
                    return null
                }
                return [...reportTasks].sort((a, b) => {
                    const aInMotion = !TERMINAL_RUN_STATUSES.includes(
                        a.task.latest_run?.status ?? TaskRunStatus.NOT_STARTED
                    )
                    const bInMotion = !TERMINAL_RUN_STATUSES.includes(
                        b.task.latest_run?.status ?? TaskRunStatus.NOT_STARTED
                    )
                    if (aInMotion !== bInMotion) {
                        return aInMotion ? -1 : 1
                    }
                    return new Date(b.startedAt).getTime() - new Date(a.startedAt).getTime()
                })[0]
            },
        ],
        // The linked task the viewer renders: the explicit selection if it still exists, else `primaryTask`.
        selectedTask: [
            (s) => [s.reportTasks, s.selectedTaskId, s.primaryTask],
            (
                reportTasks: ReportTaskEntry[] | null,
                selectedTaskId: string | null,
                primaryTask: ReportTaskEntry | null
            ): ReportTaskEntry | null => reportTasks?.find((rt) => rt.task.id === selectedTaskId) ?? primaryTask,
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
        // The artefact log is the single source for the activity timeline AND the task associations,
        // so deriving the linked tasks hangs off each successful artefact load rather than issuing a
        // second identical fetch. The branch diff also cascades from here (once artefacts resolve we
        // know the latest commit artefact), but only re-fetches when a *new* commit lands.
        loadReportArtefactsSuccess: () => {
            actions.loadReportTasks()
            const commit = values.latestCommitArtefact
            if (commit && commit.id !== values.diffArtefactId) {
                actions.loadReportDiff({ artefactId: commit.id })
            }
            // The review conversation cascades off the same commit artefact as the diff, but only when
            // the report has a shipped implementation PR — otherwise there's nothing to resolve.
            if (commit && commit.id !== values.reviewCommentsArtefactId && values.report?.implementation_pr_url) {
                actions.loadReportReviewComments({ artefactId: commit.id })
            }
        },
        // Poll the artefact log only while the report is active; stop once it reaches a terminal status
        // (or is unloaded). Tasks are re-derived via `loadReportArtefactsSuccess`. Mirrors desktop
        // `useReportTasks` gating. The keyed disposable replaces any running interval on re-add and is
        // torn down automatically on unmount / tab hide.
        setReport: () => {
            if (values.isReportActive) {
                cache.disposables.add(() => {
                    const interval = setInterval(() => actions.loadReportArtefacts(), REPORT_TASKS_POLL_INTERVAL_MS)
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
        // `loadReportTasks` is cascaded from `loadReportArtefactsSuccess`, so it isn't called here.
        actions.loadReportArtefacts()
        actions.loadReportSignals()
        actions.loadAvailableReviewers()
        // Seed the report from props so polling is gated on its status from the first tick.
        actions.setReport(props.report ?? null)
    }),
])
