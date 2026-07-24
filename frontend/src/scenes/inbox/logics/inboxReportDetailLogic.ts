import {
    MakeLogicType,
    actions,
    afterMount,
    connect,
    kea,
    key,
    listeners,
    path,
    props,
    propsChanged,
    reducers,
    selectors,
} from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { SignalNode } from 'scenes/debug/signals/types'
import { personalIntegrationsLogic } from 'scenes/settings/user/personalIntegrationsLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { Task, TaskRunStatus } from 'products/posthog_ai/frontend/types/taskTypes'
import {
    signalsReportArtefactsDiff,
    signalsReportPrChecks,
    signalsReportPrComments,
    signalsReportPrMerge,
    signalsReportPrMergeReadiness,
    signalsReportPrReviewCommentDestroy,
    signalsReportPrReviewCommentReactionDestroy,
    signalsReportPrReviewCommentReactionsCreate,
    signalsReportPrReviewCommentsCreate,
    signalsReportPrReviewCommentUpdate,
    signalsReportsSignalsRetrieve,
} from 'products/signals/frontend/generated/api'
import type {
    CommitDiffResponseApi,
    MergeMethodEnumApi,
    PullRequestCheckApi,
    PullRequestCommentApi,
    PullRequestCommentReactionApi,
    PullRequestMergeReadinessApi,
} from 'products/signals/frontend/generated/api.schemas'

import type { SignalNodeApi } from '../../../../../products/signals/frontend/generated/api.schemas'
import type { PersonalGitHubIntegration } from '../../settings/user/personalIntegrationsLogic'
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

// PR CI checks refresh cadence while the detail is open — a running build's status stays current
// without hammering GitHub. Mirrors the desktop PR-review view's 15s poll.
const PR_CHECKS_POLL_INTERVAL_MS = 15000

/** Extract the PR url from a task's latest run output, if present. Mirrors desktop `getTaskPrUrl`. */
export function getTaskPrUrl(task: Task): string | null {
    const prUrl = task.latest_run?.output?.pr_url
    return typeof prUrl === 'string' && prUrl.length > 0 ? prUrl : null
}

/**
 * A PR comment plus client-only state layered on top of the generated shape: `pending` marks an
 * optimistic create/edit still in flight (or failed), so the UI can show it immediately instead of
 * letting it vanish during the request.
 */
export interface ClientPullRequestComment extends PullRequestCommentApi {
    pending?: 'sending' | 'failed'
}

/** An inline review-comment thread anchored to a diff line: the root comment plus its replies, in order. */
export interface ReviewThread {
    /** Root comment id — the id GitHub reply calls target. */
    rootId: string
    path: string
    /** Anchor line in the diff (the end line for multi-line comments). */
    line: number
    /** GitHub diff side: 'RIGHT' = additions, 'LEFT' = deletions. */
    side: 'LEFT' | 'RIGHT'
    comments: ClientPullRequestComment[]
}

/** A not-yet-posted thread the user opened on a diff line. */
export interface DraftThread {
    path: string
    line: number
    side: 'LEFT' | 'RIGHT'
}

/** Stable key for a thread or draft anchor, used for posting state and annotation metadata. */
export function threadKey(anchor: { path: string; line: number; side: string }): string {
    return `${anchor.path}:${anchor.side}:${anchor.line}`
}

/** Pull the most specific message out of a review-comment API error, falling back to `fallback`. */
function reviewCommentError(error: any, fallback: string): string {
    return error?.data?.error || error?.detail || error?.message || fallback
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

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface inboxReportDetailLogicValues {
    personalIntegrations: PersonalGitHubIntegration[] // personalIntegrationsLogic
    actionabilityExplanation: string | null
    addReviewerOptions: AvailableReviewerOption[]
    availableReviewers: AvailableReviewerOption[] | null
    availableReviewersLoading: boolean
    currentUserGithubLogin: string | null
    diffArtefactId: string | null
    displayReviewers: EnrichedReviewer[] | null
    draftThread: DraftThread | null
    editingCommentId: string | null
    expandedTaskIds: string[]
    hasImplementationPr: boolean
    hasPersonalGithub: boolean
    inlineThreadCount: number
    inlineThreadsByFile: Record<string, ReviewThread[]>
    isReResearch: boolean
    isReportActive: boolean
    isUpdatingReviewers: boolean
    latestCommitArtefact: SignalReportArtefact | null
    merging: boolean
    optimisticReviewers: EnrichedReviewer[] | null
    postingThreadKey: string | null
    prChecks: readonly PullRequestCheckApi[] | null
    prChecksError: string | null
    prChecksLoading: boolean
    prComments: readonly PullRequestCommentApi[] | null
    prCommentsError: string | null
    prCommentsLoading: boolean
    prMergeReadiness: PullRequestMergeReadinessApi | null
    prMergeReadinessLoading: boolean
    primaryTask: ReportTaskEntry | null
    priorityExplanation: string | null
    report: SignalReport | null
    reportArtefacts: SignalReportArtefact[] | null
    reportArtefactsLoading: boolean
    reportDiff: CommitDiffResponseApi | null
    reportDiffError: string | null
    reportDiffLoading: boolean
    reportReviewers: EnrichedReviewer[] | null
    reportSignals: SignalNode[] | null
    reportSignalsLoading: boolean
    reportTasks: ReportTaskEntry[] | null
    reportTasksLoading: boolean
    selectedTask: ReportTaskEntry | null
    selectedTaskId: string | null
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface inboxReportDetailLogicActions {
    approveAndMerge: () => {
        value: true
    }
    armAutoMerge: () => {
        value: true
    }
    cancelAutoMerge: () => {
        value: true
    }
    closeDraftThread: () => {
        value: true
    }
    deleteReviewComment: (commentId: string) => {
        commentId: string
    }
    editReviewComment: (
        commentId: string,
        body: string
    ) => {
        body: string
        commentId: string
    }
    loadAvailableReviewers: ({ query }?: { query?: string }) => {
        query?: string
    }
    loadAvailableReviewersFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadAvailableReviewersSuccess: (
        availableReviewers: {
            email: string
            name: string
            user_uuid: string
        }[],
        payload?: {
            query?: string
        }
    ) => {
        availableReviewers: {
            email: string
            name: string
            user_uuid: string
        }[]
        payload?: {
            query?: string
        }
    }
    loadPrChecks: () => any
    loadPrChecksFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadPrChecksSuccess: (
        prChecks: readonly PullRequestCheckApi[] | null,
        payload?: any
    ) => {
        prChecks: readonly PullRequestCheckApi[] | null
        payload?: any
    }
    loadPrComments: () => any
    loadPrCommentsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadPrCommentsSuccess: (
        prComments: readonly PullRequestCommentApi[] | null,
        payload?: any
    ) => {
        prComments: readonly PullRequestCommentApi[] | null
        payload?: any
    }
    loadPrMergeReadiness: () => any
    loadPrMergeReadinessFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadPrMergeReadinessSuccess: (
        prMergeReadiness: PullRequestMergeReadinessApi | null,
        payload?: any
    ) => {
        prMergeReadiness: PullRequestMergeReadinessApi | null
        payload?: any
    }
    loadReportArtefacts: () => any
    loadReportArtefactsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadReportArtefactsSuccess: (
        reportArtefacts: SignalReportArtefact[],
        payload?: any
    ) => {
        reportArtefacts: SignalReportArtefact[]
        payload?: any
    }
    loadReportDiff: ({ artefactId }: { artefactId: string }) => {
        artefactId: string
    }
    loadReportDiffFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadReportDiffSuccess: (
        reportDiff: CommitDiffResponseApi | null,
        payload?: {
            artefactId: string
        }
    ) => {
        reportDiff: CommitDiffResponseApi | null
        payload?: {
            artefactId: string
        }
    }
    loadReportSignals: () => any
    loadReportSignalsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadReportSignalsSuccess: (
        reportSignals: SignalNodeApi[],
        payload?: any
    ) => {
        reportSignals: SignalNodeApi[]
        payload?: any
    }
    loadReportTasks: () => any
    loadReportTasksFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadReportTasksSuccess: (
        reportTasks: ReportTaskEntry[],
        payload?: any
    ) => {
        reportTasks: ReportTaskEntry[]
        payload?: any
    }
    mergePr: () => {
        value: true
    }
    openDraftThread: (draft: DraftThread) => {
        draft: DraftThread
    }
    postReviewComment: (payload: {
        body: string
        inReplyTo?: string
        /** Thread/draft key the composer belongs to, for per-thread posting state. */
        key: string
        line?: number
        path?: string
        side?: 'LEFT' | 'RIGHT'
    }) => {
        payload: {
            body: string
            inReplyTo?: string | undefined
            key: string
            line?: number | undefined
            path?: string | undefined
            side?: 'LEFT' | 'RIGHT' | undefined
        }
    }
    postReviewCommentFinished: () => {
        value: true
    }
    searchAvailableReviewers: (query: string) => {
        query: string
    }
    setEditingCommentId: (commentId: string | null) => {
        commentId: string | null
    }
    setMerging: (merging: boolean) => {
        merging: boolean
    }
    setOptimisticReviewers: (reviewers: EnrichedReviewer[] | null) => {
        reviewers: EnrichedReviewer[] | null
    }
    setReport: (report: SignalReport | null) => {
        report: SignalReport | null
    }
    setSelectedTaskId: (taskId: string | null) => {
        taskId: string | null
    }
    toggleExpandedTask: (taskId: string) => {
        taskId: string
    }
    toggleReviewCommentReaction: (
        commentId: string,
        content: string
    ) => {
        commentId: string
        content: string
    }
    updateReviewers: (
        content: Record<string, string>[],
        optimistic: EnrichedReviewer[]
    ) => {
        content: Record<string, string>[]
        optimistic: EnrichedReviewer[]
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface inboxReportDetailLogicMeta {
    key: string
    __keaTypeGenInternalSelectorTypes: {
        isUpdatingReviewers: (optimisticReviewers: EnrichedReviewer[] | null) => boolean
        reportReviewers: (reportArtefacts: SignalReportArtefact[] | null) => EnrichedReviewer[] | null
        isReportActive: (report: SignalReport | null) => boolean
        hasImplementationPr: (report: SignalReport | null) => boolean
        hasPersonalGithub: (personalIntegrations: PersonalGitHubIntegration[]) => boolean
        currentUserGithubLogin: (personalIntegrations: PersonalGitHubIntegration[]) => string | null
        inlineThreadsByFile: (prComments: readonly PullRequestCommentApi[] | null) => Record<string, ReviewThread[]>
        inlineThreadCount: (inlineThreadsByFile: Record<string, ReviewThread[]>) => number
        latestCommitArtefact: (reportArtefacts: SignalReportArtefact[] | null) => SignalReportArtefact | null
        priorityExplanation: (reportArtefacts: SignalReportArtefact[] | null) => string | null
        actionabilityExplanation: (reportArtefacts: SignalReportArtefact[] | null) => string | null
        displayReviewers: (
            reportReviewers: EnrichedReviewer[] | null,
            optimisticReviewers: EnrichedReviewer[] | null,
            user: null | import('../../../types').UserType
        ) => EnrichedReviewer[] | null
        addReviewerOptions: (
            availableReviewers: AvailableReviewerOption[] | null,
            user: null | import('../../../types').UserType
        ) => AvailableReviewerOption[]
        isReResearch: (reportTasks: ReportTaskEntry[] | null) => boolean
        primaryTask: (reportTasks: ReportTaskEntry[] | null) => ReportTaskEntry | null
        selectedTask: (
            reportTasks: ReportTaskEntry[] | null,
            selectedTaskId: string | null,
            primaryTask: ReportTaskEntry | null
        ) => ReportTaskEntry | null
    }
}

export type inboxReportDetailLogicType = MakeLogicType<
    inboxReportDetailLogicValues,
    inboxReportDetailLogicActions,
    InboxReportDetailLogicProps,
    inboxReportDetailLogicMeta
>

/**
 * Per-selected-report detail logic: artefacts, contributing signals, suggested reviewers, and linked tasks.
 * Keyed by `reportId` so each open report gets its own mounted instance. Does NOT import `inboxSceneLogic`
 * (the report id is passed in as a prop) to avoid a logic cycle.
 */
export const inboxReportDetailLogic = kea<inboxReportDetailLogicType>([
    path(['scenes', 'inbox', 'logics', 'inboxReportDetailLogic']),
    props({} as InboxReportDetailLogicProps),
    key((props) => props.reportId),

    connect(() => ({
        // Personal GitHub connection state gates the inline comment composer (comments post as the user).
        values: [personalIntegrationsLogic, ['integrations as personalIntegrations']],
    })),

    actions({
        // Open a not-yet-posted comment thread on a diff line (one draft at a time).
        openDraftThread: (draft: DraftThread) => ({ draft }),
        closeDraftThread: true,
        // Post an inline review comment: a reply when `inReplyTo` is set, else a new thread on the draft anchor.
        postReviewComment: (payload: {
            body: string
            inReplyTo?: string
            path?: string
            line?: number
            side?: 'LEFT' | 'RIGHT'
            /** Thread/draft key the composer belongs to, for per-thread posting state. */
            key: string
        }) => ({ payload }),
        postReviewCommentFinished: true,
        // Edit / delete one of the user's own review comments (optimistic, reverts on failure).
        editReviewComment: (commentId: string, body: string) => ({ commentId, body }),
        deleteReviewComment: (commentId: string) => ({ commentId }),
        // Add or remove the user's own reaction of `content` on a review comment (optimistic toggle).
        toggleReviewCommentReaction: (commentId: string, content: string) => ({ commentId, content }),
        // Which comment is being edited inline (null = none).
        setEditingCommentId: (commentId: string | null) => ({ commentId }),
        // Merge the PR now / arm auto-merge (merge once checks pass) / cancel a pending auto-merge.
        mergePr: true,
        armAutoMerge: true,
        cancelAutoMerge: true,
        // Record an approving review as the user, then merge the usual way (used when a required review
        // is the only thing blocking the merge).
        approveAndMerge: true,
        setMerging: (merging: boolean) => ({ merging }),
        setReport: (report: SignalReport | null) => ({ report }),
        // Optimistically replace the reviewer list while the PUT is in flight, then reload from the server.
        // Addressed by report (not artefact) so a report with no reviewers yet can still be assigned one.
        // Mirrors desktop `useUpdateSuggestedReviewers` optimistic behavior.
        updateReviewers: (content: Record<string, string>[], optimistic: EnrichedReviewer[]) => ({
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
                    const response = await signalsReportsSignalsRetrieve(
                        String(teamLogic.values.currentTeamId),
                        props.reportId
                    )
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
        // CI checks on the report's implementation PR. Only fetched when the report has one; polled
        // every 15s while the detail is mounted (see the `setReport` listener) so a running build's
        // status stays current, mirroring the desktop PR-review view.
        prChecks: [
            null as readonly PullRequestCheckApi[] | null,
            {
                loadPrChecks: async () => {
                    const teamId = teamLogic.values.currentTeamId
                    if (!teamId) {
                        return null
                    }
                    const response = await signalsReportPrChecks(String(teamId), props.reportId)
                    return response.checks
                },
            },
        ],
        // Conversation + review comments on the report's implementation PR, merged chronologically.
        prComments: [
            null as readonly PullRequestCommentApi[] | null,
            {
                loadPrComments: async () => {
                    const teamId = teamLogic.values.currentTeamId
                    if (!teamId) {
                        return null
                    }
                    const response = await signalsReportPrComments(String(teamId), props.reportId)
                    return response.comments
                },
            },
        ],
        // Mergeability + CI + auto-merge availability for the report's PR — drives the merge control.
        prMergeReadiness: [
            null as PullRequestMergeReadinessApi | null,
            {
                loadPrMergeReadiness: async () => {
                    const teamId = teamLogic.values.currentTeamId
                    if (!teamId) {
                        return null
                    }
                    const response = await signalsReportPrMergeReadiness(String(teamId), props.reportId)
                    return response.readiness
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
        // Human-readable PR checks/comments load failures (kea-loaders only exposes a boolean flag).
        // A failure usually means the branch/PR was deleted or the GitHub integration lost access.
        prChecksError: [
            null as string | null,
            {
                loadPrChecks: () => null,
                loadPrChecksSuccess: () => null,
                loadPrChecksFailure: () => "Couldn't load the PR checks from GitHub.",
            },
        ],
        prCommentsError: [
            null as string | null,
            {
                loadPrComments: () => null,
                loadPrCommentsSuccess: () => null,
                loadPrCommentsFailure: () => "Couldn't load the PR comments from GitHub.",
            },
        ],
        // The one in-progress draft thread on a diff line. Reset when the report changes.
        draftThread: [
            null as DraftThread | null,
            {
                openDraftThread: (_, { draft }) => draft,
                closeDraftThread: () => null,
                setReport: () => null,
            },
        ],
        // Which thread's composer has a post in flight — gates its submit button and textarea.
        postingThreadKey: [
            null as string | null,
            {
                postReviewComment: (_, { payload }) => payload.key,
                postReviewCommentFinished: () => null,
            },
        ],
        // Which comment is open for inline editing. Cleared on a successful edit or when the report changes.
        editingCommentId: [
            null as string | null,
            {
                setEditingCommentId: (_, { commentId }) => commentId,
                setReport: () => null,
            },
        ],
        // In-flight guard for the merge control, so a merge/auto-merge action can't be double-fired.
        merging: [
            false,
            {
                setMerging: (_, { merging }) => merging,
            },
        ],
    }),

    selectors({
        // Mirrors the optimistic override lifecycle: an update is in flight exactly while the
        // optimistic list is set (cleared once the reload lands or the update fails).
        isUpdatingReviewers: [
            (s) => [s.optimisticReviewers],
            (optimisticReviewers: EnrichedReviewer[] | null) => optimisticReviewers !== null,
        ],
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
        // Whether the report has a shipped implementation PR — gates the PR checks/comments fetch + poll.
        hasImplementationPr: [
            (s) => [s.report],
            (report: SignalReport | null): boolean => !!report?.implementation_pr_url,
        ],
        // Whether the current user has a personal GitHub connection — required to post review comments
        // (they're attributed to the user's own GitHub identity, not the app's).
        hasPersonalGithub: [
            (s) => [s.personalIntegrations],
            (personalIntegrations: PersonalGitHubIntegration[]): boolean => (personalIntegrations ?? []).length > 0,
        ],
        // The current user's GitHub login (from their personal connection) — used to attribute optimistic
        // comments and to tell which comments/reactions are the user's own (editable/removable). Note this
        // is `github_login`, NOT `account.name` (which is the installation's org/user, e.g. "PostHog").
        currentUserGithubLogin: [
            (s) => [s.personalIntegrations],
            (personalIntegrations: PersonalGitHubIntegration[]): string | null =>
                personalIntegrations?.[0]?.github_login ?? null,
        ],
        // Inline review threads grouped by file path: thread roots (review comments with a line anchor
        // and no in_reply_to) plus their replies, in chronological order. Outdated comments (null line)
        // are excluded here — they still show in the Comments section.
        inlineThreadsByFile: [
            (s) => [s.prComments],
            (prComments: readonly PullRequestCommentApi[] | null): Record<string, ReviewThread[]> => {
                if (!prComments) {
                    return {}
                }
                const threads = new Map<string, ReviewThread>()
                for (const comment of prComments) {
                    if (comment.comment_type !== 'review' || !comment.path || comment.in_reply_to_id) {
                        continue
                    }
                    if (comment.line == null) {
                        continue
                    }
                    threads.set(comment.id, {
                        rootId: comment.id,
                        path: comment.path,
                        line: comment.line,
                        side: comment.side === 'LEFT' ? 'LEFT' : 'RIGHT',
                        comments: [comment],
                    })
                }
                for (const comment of prComments) {
                    if (comment.comment_type !== 'review' || !comment.in_reply_to_id) {
                        continue
                    }
                    threads.get(comment.in_reply_to_id)?.comments.push(comment)
                }
                const byFile: Record<string, ReviewThread[]> = {}
                for (const thread of threads.values()) {
                    ;(byFile[thread.path] ??= []).push(thread)
                }
                return byFile
            },
        ],
        // Total inline threads, for the Files changed toolbar summary.
        inlineThreadCount: [
            (s) => [s.inlineThreadsByFile],
            (inlineThreadsByFile: Record<string, ReviewThread[]>): number =>
                Object.values(inlineThreadsByFile).reduce((sum, threads) => sum + threads.length, 0),
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
        updateReviewers: async ({ content }) => {
            try {
                await api.signalReports.setReviewers(props.reportId, content)
                await actions.loadReportArtefacts()
            } catch (error: any) {
                lemonToast.error(error?.detail || error?.message || 'Failed to update reviewers')
            } finally {
                // Clear the optimistic override; the freshly-loaded artefact is now the source of truth.
                actions.setOptimisticReviewers(null)
            }
        },
        // Post an inline review comment as the user. The comment is inserted optimistically (marked
        // `pending: 'sending'`) and the composer/draft closes immediately, so nothing vanishes during
        // the request. On success the optimistic entry is replaced by the real comment; on failure it's
        // flagged `pending: 'failed'` (kept visible so the text isn't lost) and a toast explains why.
        postReviewComment: async ({ payload }) => {
            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                return
            }
            const tempId = `optimistic-${payload.key}-${values.prComments?.length ?? 0}-${payload.body.length}`
            const login = values.currentUserGithubLogin
            const optimistic: ClientPullRequestComment = {
                id: tempId,
                pending: 'sending',
                author: login,
                author_avatar_url: login ? `https://github.com/${login}.png` : null,
                body: payload.body,
                created_at: new Date().toISOString(),
                url: null,
                comment_type: 'review',
                path: payload.path ?? null,
                line: payload.line ?? null,
                start_line: null,
                side: payload.side ?? 'RIGHT',
                diff_hunk: null,
                in_reply_to_id: payload.inReplyTo ?? null,
                commit_id: null,
                reactions: [],
            }
            actions.loadPrCommentsSuccess([...(values.prComments ?? []), optimistic])
            actions.closeDraftThread()
            try {
                const response = await signalsReportPrReviewCommentsCreate(String(teamId), props.reportId, {
                    body: payload.body,
                    in_reply_to: payload.inReplyTo ?? null,
                    path: payload.path ?? null,
                    line: payload.line ?? null,
                    side: payload.side ?? null,
                })
                actions.loadPrCommentsSuccess(
                    (values.prComments ?? []).map((c) => (c.id === tempId ? response.comment : c))
                )
            } catch (error: any) {
                actions.loadPrCommentsSuccess(
                    (values.prComments ?? []).map((c) =>
                        c.id === tempId ? { ...(c as ClientPullRequestComment), pending: 'failed' } : c
                    )
                )
                lemonToast.error(reviewCommentError(error, "Couldn't post the comment to GitHub"))
            } finally {
                actions.postReviewCommentFinished()
            }
        },
        // Edit one of the user's own review comments. Optimistically swaps the body in, reverts the whole
        // list on failure so nothing is half-applied.
        editReviewComment: async ({ commentId, body }) => {
            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                return
            }
            const prev = values.prComments ?? []
            actions.setEditingCommentId(null)
            actions.loadPrCommentsSuccess(
                prev.map((c) =>
                    c.id === commentId ? { ...(c as ClientPullRequestComment), body, pending: 'sending' } : c
                )
            )
            try {
                const response = await signalsReportPrReviewCommentUpdate(String(teamId), props.reportId, commentId, {
                    body,
                })
                actions.loadPrCommentsSuccess(
                    (values.prComments ?? []).map((c) => (c.id === commentId ? response.comment : c))
                )
            } catch (error: any) {
                actions.loadPrCommentsSuccess(prev)
                lemonToast.error(reviewCommentError(error, "Couldn't save the edit"))
            }
        },
        // Delete one of the user's own review comments. Optimistically removes it; restores on failure.
        deleteReviewComment: async ({ commentId }) => {
            const teamId = teamLogic.values.currentTeamId
            if (!teamId) {
                return
            }
            const prev = values.prComments ?? []
            actions.loadPrCommentsSuccess(prev.filter((c) => c.id !== commentId))
            try {
                await signalsReportPrReviewCommentDestroy(String(teamId), props.reportId, commentId)
            } catch (error: any) {
                actions.loadPrCommentsSuccess(prev)
                lemonToast.error(reviewCommentError(error, "Couldn't delete the comment"))
            }
        },
        // Toggle the user's own reaction of `content` on a comment. Optimistically adds/removes the
        // reaction, then confirms with the server (add returns the real reaction id); reverts on failure.
        toggleReviewCommentReaction: async ({ commentId, content }) => {
            const teamId = teamLogic.values.currentTeamId
            const login = values.currentUserGithubLogin
            if (!teamId || !login) {
                return
            }
            const prev = values.prComments ?? []
            const comment = prev.find((c) => c.id === commentId)
            const mine = comment?.reactions?.find((r) => r.content === content && r.user_login === login)
            const setReactions = (
                list: readonly PullRequestCommentApi[],
                reactions: PullRequestCommentReactionApi[]
            ): PullRequestCommentApi[] => list.map((c) => (c.id === commentId ? { ...c, reactions } : c))

            if (mine) {
                actions.loadPrCommentsSuccess(
                    setReactions(
                        prev,
                        (comment?.reactions ?? []).filter((r) => r.id !== mine.id)
                    )
                )
                try {
                    await signalsReportPrReviewCommentReactionDestroy(
                        String(teamId),
                        props.reportId,
                        commentId,
                        mine.id
                    )
                } catch (error: any) {
                    actions.loadPrCommentsSuccess(prev)
                    lemonToast.error(reviewCommentError(error, "Couldn't remove the reaction"))
                }
                return
            }

            const tempId = `optimistic-rx-${commentId}-${content}`
            const optimisticReaction: PullRequestCommentReactionApi = { id: tempId, content, user_login: login }
            actions.loadPrCommentsSuccess(setReactions(prev, [...(comment?.reactions ?? []), optimisticReaction]))
            try {
                const response = await signalsReportPrReviewCommentReactionsCreate(
                    String(teamId),
                    props.reportId,
                    commentId,
                    { content: content as any }
                )
                actions.loadPrCommentsSuccess(
                    (values.prComments ?? []).map((c) =>
                        c.id === commentId
                            ? {
                                  ...c,
                                  reactions: (c.reactions ?? []).map((r) => (r.id === tempId ? response.reaction : r)),
                              }
                            : c
                    )
                )
            } catch (error: any) {
                actions.loadPrCommentsSuccess(prev)
                lemonToast.error(reviewCommentError(error, "Couldn't add the reaction"))
            }
        },
        // Merge the PR now — guarded against a moved branch by the head sha we last read, using the
        // repo's default merge method. On success the report resolves server-side, so reload artefacts
        // (the shell re-reads status from there) and the readiness so the control shows the merged state.
        mergePr: async () => {
            const teamId = teamLogic.values.currentTeamId
            const readiness = values.prMergeReadiness
            if (!teamId || !readiness || values.merging) {
                return
            }
            actions.setMerging(true)
            try {
                await signalsReportPrMerge(String(teamId), props.reportId, {
                    merge_mode: 'merge',
                    sha: readiness.head_sha ?? undefined,
                    merge_method: (readiness.merge_method as MergeMethodEnumApi | null) ?? undefined,
                })
                lemonToast.success('Pull request merged')
                actions.loadReportArtefacts()
            } catch (error: any) {
                lemonToast.error(reviewCommentError(error, "Couldn't merge the pull request"))
            } finally {
                actions.setMerging(false)
                actions.loadPrMergeReadiness()
            }
        },
        // Approve the PR as the user, then merge the usual way: merge now when checks are already green,
        // or arm auto-merge when they're still pending. GitHub re-evaluates mergeability at merge time,
        // so the direct merge is safe right after the approval lands.
        approveAndMerge: async () => {
            const teamId = teamLogic.values.currentTeamId
            const readiness = values.prMergeReadiness
            if (!teamId || !readiness?.node_id || values.merging) {
                return
            }
            actions.setMerging(true)
            try {
                await signalsReportPrMerge(String(teamId), props.reportId, {
                    merge_mode: 'approve',
                    node_id: readiness.node_id,
                })
                const method = (readiness.merge_method as MergeMethodEnumApi | null) ?? undefined
                if (readiness.ci_status === 'pending' && readiness.auto_merge_allowed) {
                    await signalsReportPrMerge(String(teamId), props.reportId, {
                        merge_mode: 'auto_merge',
                        node_id: readiness.node_id,
                        merge_method: method,
                    })
                    lemonToast.success('Approved. Auto-merge armed — this PR will merge once checks pass')
                } else {
                    await signalsReportPrMerge(String(teamId), props.reportId, {
                        merge_mode: 'merge',
                        sha: readiness.head_sha ?? undefined,
                        merge_method: method,
                    })
                    lemonToast.success('Approved and merged')
                    actions.loadReportArtefacts()
                }
            } catch (error: any) {
                lemonToast.error(reviewCommentError(error, "Couldn't approve and merge the pull request"))
            } finally {
                actions.setMerging(false)
                actions.loadPrMergeReadiness()
            }
        },
        // Arm GitHub-native auto-merge (merges once required checks pass), as the user.
        armAutoMerge: async () => {
            const teamId = teamLogic.values.currentTeamId
            const readiness = values.prMergeReadiness
            if (!teamId || !readiness?.node_id || values.merging) {
                return
            }
            actions.setMerging(true)
            try {
                await signalsReportPrMerge(String(teamId), props.reportId, {
                    merge_mode: 'auto_merge',
                    node_id: readiness.node_id,
                    merge_method: (readiness.merge_method as MergeMethodEnumApi | null) ?? undefined,
                })
                lemonToast.success('Auto-merge armed — this PR will merge once checks pass')
            } catch (error: any) {
                lemonToast.error(reviewCommentError(error, "Couldn't arm auto-merge"))
            } finally {
                actions.setMerging(false)
                actions.loadPrMergeReadiness()
            }
        },
        // Disarm a previously-armed auto-merge.
        cancelAutoMerge: async () => {
            const teamId = teamLogic.values.currentTeamId
            const readiness = values.prMergeReadiness
            if (!teamId || !readiness?.node_id || values.merging) {
                return
            }
            actions.setMerging(true)
            try {
                await signalsReportPrMerge(String(teamId), props.reportId, {
                    merge_mode: 'cancel_auto_merge',
                    node_id: readiness.node_id,
                })
                lemonToast.success('Auto-merge cancelled')
            } catch (error: any) {
                lemonToast.error(reviewCommentError(error, "Couldn't cancel auto-merge"))
            } finally {
                actions.setMerging(false)
                actions.loadPrMergeReadiness()
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
            // Load the PR checks/comments once the report has a shipped PR. The recurring checks poll
            // is registered once in `afterMount` (not here) so it isn't torn down and restarted every
            // time the shell hands us a fresh `report` prop — which would starve the 15s cadence.
            if (values.hasImplementationPr) {
                if (values.prChecks === null && !values.prChecksLoading) {
                    actions.loadPrChecks()
                }
                if (values.prComments === null && !values.prCommentsLoading) {
                    actions.loadPrComments()
                }
                if (values.prMergeReadiness === null && !values.prMergeReadinessLoading) {
                    actions.loadPrMergeReadiness()
                }
            }
        },
    })),

    propsChanged(({ actions, props }, oldProps) => {
        // The shell re-renders the detail with a refreshed `selectedReport`; re-gate polling on the new status.
        if (props.report !== oldProps.report) {
            actions.setReport(props.report ?? null)
        }
    }),

    afterMount(({ actions, props, values, cache }) => {
        // `loadReportTasks` is cascaded from `loadReportArtefactsSuccess`, so it isn't called here.
        actions.loadReportArtefacts()
        actions.loadReportSignals()
        actions.loadAvailableReviewers()
        // Seed the report from props so polling is gated on its status from the first tick.
        actions.setReport(props.report ?? null)
        // Register the PR-checks poll once for the lifetime of the mount — the tick re-checks whether
        // the report has a PR, so it stays correct as the report prop churns without the interval ever
        // being torn down and restarted (which would keep resetting the 15s cadence). Auto-disposed on
        // unmount / hidden tab.
        cache.disposables.add(() => {
            const interval = setInterval(() => {
                if (values.hasImplementationPr) {
                    actions.loadPrChecks()
                    actions.loadPrMergeReadiness()
                }
            }, PR_CHECKS_POLL_INTERVAL_MS)
            return () => clearInterval(interval)
        }, 'prChecksPoll')
    }),
])
