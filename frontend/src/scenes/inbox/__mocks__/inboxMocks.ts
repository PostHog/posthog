// Rich mock data for Inbox Storybook stories. Covers the full range of report
// shapes the polish work needs: every priority / actionability / status, the
// three tab types (reports / pull requests / runs), suggested-reviewer ("for
// you") reports, conventional-commit titles, and varying agent-run volume.

import { SignalNode } from 'scenes/debug/signals/types'

import { SignalReport, SignalReportStatus } from '../types'

const BASE_DATE = '2026-06-10T12:00:00Z'

let idCounter = 0
function nextId(): string {
    idCounter += 1
    return `019e64b8-0000-7000-8000-${String(idCounter).padStart(12, '0')}`
}

export function makeReport(overrides: Partial<SignalReport> = {}): SignalReport {
    return {
        id: nextId(),
        title: 'Untitled report',
        summary: null,
        status: SignalReportStatus.READY,
        total_weight: 1.0,
        signal_count: 1,
        relevant_user_count: null,
        created_at: BASE_DATE,
        updated_at: BASE_DATE,
        artefact_count: 0,
        is_suggested_reviewer: false,
        priority: null,
        actionability: null,
        already_addressed: null,
        source_products: [],
        implementation_pr_url: null,
        ...overrides,
    }
}

// ── Reports tab ─────────────────────────────────────────────────────────────

export const reportTabReports: SignalReport[] = [
    makeReport({
        title: 'fix(invites): Handle incomplete recipient data in team invite form',
        summary:
            'Team invite submissions fail when the recipient list is missing an email, throwing a 500 that users see as a generic "Something went wrong".',
        status: SignalReportStatus.READY,
        priority: 'P1',
        actionability: 'immediately_actionable',
        total_weight: 3.4,
        signal_count: 12,
        relevant_user_count: 47,
        source_products: ['error_tracking'],
        is_suggested_reviewer: true,
    }),
    makeReport({
        title: 'fix(billing): Checkout API timeout during payment session creation',
        summary:
            'Checkout occasionally times out while creating the Stripe payment session, blocking upgrades. Spikes correlate with high-traffic windows.',
        status: SignalReportStatus.READY,
        priority: 'P0',
        actionability: 'immediately_actionable',
        total_weight: 5.8,
        signal_count: 31,
        relevant_user_count: 118,
        source_products: ['error_tracking', 'session_replay'],
    }),
    makeReport({
        title: 'PDF preview render failure for uploaded files',
        summary:
            'Uploaded PDFs intermittently fail to render a preview, leaving customers unable to inspect files before sharing.',
        status: SignalReportStatus.READY,
        priority: 'P2',
        actionability: 'requires_human_input',
        total_weight: 2.1,
        signal_count: 8,
        relevant_user_count: 23,
        source_products: ['session_replay'],
        is_suggested_reviewer: true,
    }),
    makeReport({
        title: 'feat(onboarding): Users drop off at the SDK install step',
        summary:
            'A large share of new projects never send a first event – most stall on the SDK install step of onboarding.',
        status: SignalReportStatus.READY,
        priority: 'P3',
        actionability: 'requires_human_input',
        total_weight: 1.6,
        signal_count: 5,
        relevant_user_count: 210,
        source_products: ['session_replay', 'llm_analytics'],
    }),
    makeReport({
        title: 'Slow dashboard load for large cohorts',
        summary:
            'Dashboards with large cohort filters take 10s+ to load; users abandon before the first insight renders.',
        status: SignalReportStatus.CANDIDATE,
        priority: null,
        actionability: null,
        total_weight: 0.9,
        signal_count: 3,
        relevant_user_count: 14,
        source_products: ['session_replay'],
    }),
    makeReport({
        title: 'Zendesk: recurring "export stuck" tickets',
        summary: null,
        status: SignalReportStatus.CANDIDATE,
        priority: 'P4',
        actionability: 'not_actionable',
        total_weight: 1.2,
        signal_count: 6,
        relevant_user_count: 9,
        source_products: ['zendesk'],
    }),
]

// ── Pull requests tab ───────────────────────────────────────────────────────

export const pullRequestReports: SignalReport[] = [
    makeReport({
        title: 'fix(invites): validate recipient payload before submit',
        summary: 'Adds client + server validation rejecting incomplete invite rows, with a clear inline error.',
        status: SignalReportStatus.READY,
        priority: 'P1',
        actionability: 'immediately_actionable',
        total_weight: 3.4,
        signal_count: 12,
        source_products: ['error_tracking'],
        implementation_pr_url: 'https://github.com/PostHog/posthog/pull/12001',
        is_suggested_reviewer: true,
    }),
    makeReport({
        title: 'fix(billing): add retry + timeout to checkout session creation',
        summary: 'Wraps the Stripe session call in a bounded retry and surfaces a retryable error to the client.',
        status: SignalReportStatus.READY,
        priority: 'P0',
        actionability: 'immediately_actionable',
        total_weight: 5.8,
        signal_count: 31,
        source_products: ['error_tracking'],
        implementation_pr_url: 'https://github.com/PostHog/posthog/pull/12002',
    }),
    makeReport({
        title: 'perf(dashboards): paginate cohort filter resolution',
        summary: 'Resolves large cohort filters in pages to keep dashboard first-render under 2s.',
        status: SignalReportStatus.READY,
        priority: 'P2',
        actionability: 'immediately_actionable',
        total_weight: 2.0,
        signal_count: 7,
        source_products: ['session_replay'],
        implementation_pr_url: 'https://github.com/PostHog/posthog/pull/12003',
        is_suggested_reviewer: true,
    }),
]

// ── Runs tab (queued / live / finished) ─────────────────────────────────────

const queuedRuns: SignalReport[] = [
    makeReport({
        title: 'Investigate spike in 429s from the events API',
        status: SignalReportStatus.POTENTIAL,
        priority: null,
        total_weight: 0.6,
        signal_count: 2,
        source_products: ['error_tracking'],
    }),
    makeReport({
        title: 'Recurring slow query on persons page',
        status: SignalReportStatus.CANDIDATE,
        priority: 'P3',
        total_weight: 1.1,
        signal_count: 4,
        source_products: ['session_replay'],
    }),
]

const liveRuns: SignalReport[] = [
    makeReport({
        title: 'fix(auth): session dropped after SSO redirect',
        summary: 'Researching why some SSO logins land on a logged-out state after the redirect hop.',
        status: SignalReportStatus.IN_PROGRESS,
        priority: 'P1',
        total_weight: 3.0,
        signal_count: 9,
        signals_at_run: 9,
        source_products: ['error_tracking', 'session_replay'],
    }),
    makeReport({
        title: 'feat(search): empty results for valid queries',
        status: SignalReportStatus.IN_PROGRESS,
        priority: 'P2',
        total_weight: 2.4,
        signal_count: 6,
        signals_at_run: 6,
        source_products: ['session_replay'],
    }),
    makeReport({
        title: 'fix(exports): CSV export truncates at 10k rows',
        summary: 'Needs a product decision on whether to stream or cap; pausing for input.',
        status: SignalReportStatus.PENDING_INPUT,
        priority: 'P2',
        total_weight: 2.2,
        signal_count: 5,
        signals_at_run: 5,
        source_products: ['zendesk', 'error_tracking'],
    }),
]

const finishedRuns: SignalReport[] = [
    makeReport({
        title: 'fix(invites): validate recipient payload before submit',
        status: SignalReportStatus.READY,
        priority: 'P1',
        actionability: 'immediately_actionable',
        total_weight: 3.4,
        signal_count: 12,
        source_products: ['error_tracking'],
        implementation_pr_url: 'https://github.com/PostHog/posthog/pull/12001',
    }),
    makeReport({
        title: 'Investigate webhook delivery failures',
        status: SignalReportStatus.FAILED,
        priority: 'P2',
        total_weight: 1.8,
        signal_count: 5,
        source_products: ['error_tracking'],
    }),
    makeReport({
        title: 'perf(dashboards): paginate cohort filter resolution',
        status: SignalReportStatus.READY,
        priority: 'P2',
        actionability: 'immediately_actionable',
        total_weight: 2.0,
        signal_count: 7,
        source_products: ['session_replay'],
        implementation_pr_url: 'https://github.com/PostHog/posthog/pull/12003',
    }),
]

/** Lots of agents in motion: full queued + live + finished history. */
export const runReportsMany: SignalReport[] = [...queuedRuns, ...liveRuns, ...finishedRuns]
/** Just one agent live, nothing queued, a little history. */
export const runReportsFew: SignalReport[] = [liveRuns[0], finishedRuns[0]]

export const allReports: SignalReport[] = [...reportTabReports, ...pullRequestReports, ...runReportsMany]

// ── Detail-endpoint payloads ────────────────────────────────────────────────

export function mockSignals(reportId: string, count = 4): SignalNode[] {
    return Array.from({ length: count }).map((_, i) => ({
        signal_id: `${reportId}-sig-${i}`,
        content: [
            'User clicked **Submit** with an empty recipient row; the request returned `500` from `/api/invites`.',
            'Session shows three retries of the same failing checkout call before the user gave up.',
            'Error fingerprint `2c6be0b` first seen 2026-05-26, now recurring ~12×/day.',
            'Support ticket references the same flow: "I keep getting an error when inviting my team".',
        ][i % 4],
        source_product: ['error_tracking', 'session_replay', 'error_tracking', 'zendesk'][i % 4],
        source_type: 'issue',
        source_id: `${reportId}-src-${i}`,
        weight: Number((1.5 - i * 0.2).toFixed(1)),
        timestamp: BASE_DATE,
        extra: {},
    }))
}

export function mockArtefacts(reportId: string): { results: any[]; count: number } {
    const results = [
        {
            id: `${reportId}-pri`,
            type: 'priority_judgment',
            content: { priority: 'P1', explanation: 'High user impact (47 affected) and a clean, low-risk fix.' },
            created_at: BASE_DATE,
        },
        {
            id: `${reportId}-act`,
            type: 'actionability_judgment',
            content: {
                actionability: 'immediately_actionable',
                already_addressed: false,
                explanation: 'The failing endpoint and validation gap are clearly identified in the findings.',
            },
            created_at: BASE_DATE,
        },
        {
            id: `${reportId}-rev`,
            type: 'suggested_reviewers',
            content: [
                {
                    github_login: 'octocat',
                    github_name: 'Octo Cat',
                    relevant_commits: [
                        {
                            sha: 'a1b2c3d4',
                            url: 'https://github.com/PostHog/posthog/commit/a1b2c3d4',
                            reason: 'Last touched the invite form',
                        },
                    ],
                    user: { id: 1, uuid: 'u-1', email: 'octo@example.com', first_name: 'Octo', last_name: 'Cat' },
                },
                {
                    github_login: 'hedgehog',
                    github_name: 'Hedge Hog',
                    relevant_commits: [],
                    user: null,
                },
            ],
            created_at: BASE_DATE,
        },
        // Task↔report associations now live in the artefact log as `task_run` artefacts; the
        // detail logic derives the Runs list + purpose from these (no more `/tasks/` endpoint).
        {
            id: `${reportId}-tr-research`,
            type: 'task_run',
            content: {
                task_id: `${reportId}-task-research`,
                run_id: `${reportId}-task-research-run`,
                product: 'signals',
                type: 'research',
            },
            created_at: BASE_DATE,
            task_id: `${reportId}-task-research`,
        },
        {
            id: `${reportId}-tr-impl`,
            type: 'task_run',
            content: {
                task_id: `${reportId}-task-impl`,
                run_id: `${reportId}-task-impl-run`,
                product: 'signals',
                type: 'implementation',
            },
            created_at: BASE_DATE,
            task_id: `${reportId}-task-impl`,
        },
        // A handful of log artefacts so the Activity timeline has something to render.
        {
            id: `${reportId}-note`,
            type: 'note',
            content: { note: 'Confirmed the validation gap reproduces on an empty recipient row.' },
            created_at: BASE_DATE,
            created_by: { id: 1, uuid: 'u-1', email: 'octo@example.com', first_name: 'Octo', last_name: 'Cat' },
        },
        {
            id: `${reportId}-commit`,
            type: 'commit',
            content: {
                repository: 'PostHog/posthog',
                branch: 'inbox/fix-invites',
                commit_sha: 'a1b2c3d4e5f6a1b2c3d4e5f6',
                message: 'fix(invites): reject empty recipient rows before submit',
            },
            created_at: BASE_DATE,
            task_id: `${reportId}-task-impl`,
        },
        // Human edits to the report's title / summary are logged as their own artefacts.
        {
            id: `${reportId}-title`,
            type: 'title_change',
            content: {
                old_title: 'Invite flow error',
                new_title: 'Empty recipient rows crash team invites',
            },
            created_at: BASE_DATE,
            created_by: { id: 1, uuid: 'u-1', email: 'octo@example.com', first_name: 'Octo', last_name: 'Cat' },
        },
        {
            id: `${reportId}-summary`,
            type: 'summary_change',
            content: {
                old_summary: 'Users hit an error when inviting their team.',
                new_summary:
                    'Submitting the invite form with an empty recipient row returns a `500` from `/api/invites`. ' +
                    'The gap is missing client-side validation before submit.',
            },
            created_at: BASE_DATE,
            created_by: { id: 1, uuid: 'u-1', email: 'octo@example.com', first_name: 'Octo', last_name: 'Cat' },
        },
    ]
    return { results, count: results.length }
}

function makeTaskRun(taskId: string, runId: string, status: string): any {
    return {
        id: runId,
        task: taskId,
        stage: null,
        branch: 'inbox/fix-invites',
        status,
        environment: 'cloud',
        log_url: null,
        error_message: null,
        output: taskId.includes('impl') ? { pr_url: 'https://github.com/PostHog/posthog/pull/12001' } : {},
        state: {},
        artifacts: [],
        created_at: BASE_DATE,
        updated_at: BASE_DATE,
        completed_at: status === 'in_progress' ? null : BASE_DATE,
    }
}

// `runStatus` overrides the linked run's status; defaults keep the research task finished and the
// implementation task live. Pass a terminal status (e.g. 'completed') to render the run viewer's
// static replay rather than a live SSE stream.
export function mockTask(taskId: string, runStatus?: string): any {
    const status = runStatus ?? (taskId.includes('research') ? 'completed' : 'in_progress')
    return {
        id: taskId,
        task_number: 42,
        slug: 'inbox-task',
        title: taskId.includes('impl') ? 'Implement invite validation fix' : 'Research invite failures',
        description: 'Auto-created from an Inbox report.',
        origin_product: 'signal_report',
        repository: 'PostHog/posthog',
        github_integration: 1,
        json_schema: null,
        internal: false,
        latest_run: makeTaskRun(taskId, `${taskId}-run`, status),
        created_at: BASE_DATE,
        updated_at: BASE_DATE,
        created_by: null,
    }
}

/** The run-status payload (`/runs/:runId`) the `ReadonlyRunSurface` reads before replaying its log. */
export function mockTaskRun(taskId: string, runId: string): any {
    return makeTaskRun(taskId, runId, 'completed')
}

/**
 * A single-message agent run log as JSONL — what the `/runs/:runId/logs` endpoint returns (one
 * `StoredLogEntry` per line). One `agent_message` frame so the run viewer renders a single assistant
 * bubble instead of the "conversation backing run not found" error.
 */
export function mockRunLog(): string {
    const entry = {
        type: 'notification',
        notification: {
            method: 'session/update',
            params: {
                update: {
                    sessionUpdate: 'agent_message',
                    messageId: 'inbox-run-msg',
                    content: {
                        type: 'text',
                        text: 'Investigated the invite failures, confirmed the missing-recipient 500, and opened a fix.',
                    },
                },
            },
        },
    }
    return JSON.stringify(entry)
}

/**
 * A realistic multi-file unified diff for the `commit` artefact diff endpoint, matching the mocked
 * "fix invites" commit. Two TypeScript files so the rendered diff exercises Pierre's syntax
 * highlighting, hunk headers, and a multi-file layout.
 */
export function mockBranchDiff(): { diff: string; truncated: boolean } {
    const diff = `diff --git a/frontend/src/scenes/invites/inviteLogic.ts b/frontend/src/scenes/invites/inviteLogic.ts
index 1a2b3c4..5d6e7f8 100644
--- a/frontend/src/scenes/invites/inviteLogic.ts
+++ b/frontend/src/scenes/invites/inviteLogic.ts
@@ -42,9 +42,13 @@ export const inviteLogic = kea<inviteLogicType>([
     listeners(({ values, actions }) => ({
         submitInvites: async () => {
-            const recipients = values.invites
+            const recipients = values.invites.filter((invite) => invite.email.trim().length > 0)
+            if (recipients.length === 0) {
+                lemonToast.error('Add at least one recipient before sending invites.')
+                return
+            }
             await api.invites.bulkCreate(recipients)
             actions.loadInvites()
         },
     })),
diff --git a/frontend/src/scenes/invites/InviteRow.tsx b/frontend/src/scenes/invites/InviteRow.tsx
index 9c8b7a6..2f3e4d5 100644
--- a/frontend/src/scenes/invites/InviteRow.tsx
+++ b/frontend/src/scenes/invites/InviteRow.tsx
@@ -10,7 +10,7 @@ export function InviteRow({ invite, onChange }: InviteRowProps): JSX.Element {
     return (
         <div className="flex items-center gap-2">
             <LemonInput
-                value={invite.email}
+                value={invite.email}
+                status={invite.email.trim() ? undefined : 'danger'}
                 onChange={(email) => onChange({ ...invite, email })}
                 placeholder="email@example.com"
             />
         </div>
     )
 }
`
    return { diff, truncated: false }
}

export function mockCommitChecks(): {
    check_runs: { name: string; status: string; conclusion: string | null; html_url: string }[]
    rollup: string
} {
    return {
        check_runs: [
            { name: 'Backend tests', status: 'completed', conclusion: 'success', html_url: 'https://github.com' },
            { name: 'Frontend tests', status: 'completed', conclusion: 'failure', html_url: 'https://github.com' },
            { name: 'Lint', status: 'in_progress', conclusion: null, html_url: 'https://github.com' },
        ],
        rollup: 'failure',
    }
}

export const mockSourceConfigs = {
    results: [
        {
            id: 'sc-1',
            source_product: 'session_replay',
            source_type: 'session_analysis_cluster',
            enabled: true,
            config: {},
            created_at: BASE_DATE,
            updated_at: BASE_DATE,
            status: 'completed',
        },
        {
            id: 'sc-2',
            source_product: 'error_tracking',
            source_type: 'issue_created',
            enabled: true,
            config: {},
            created_at: BASE_DATE,
            updated_at: BASE_DATE,
            status: null,
        },
        {
            id: 'sc-3',
            source_product: 'github',
            source_type: 'issue',
            enabled: false,
            config: {},
            created_at: BASE_DATE,
            updated_at: BASE_DATE,
            status: null,
        },
    ],
    count: 3,
}

export const mockReviewers = {
    results: [
        { user_uuid: 'u-1', name: 'Octo Cat', email: 'octo@example.com' },
        { user_uuid: 'u-2', name: 'Hedge Hog', email: 'hedge@example.com' },
        { user_uuid: 'u-3', name: 'Max AI', email: 'max@example.com' },
    ],
    count: 3,
}

export const mockAutonomy = {
    id: 'auto-1',
    autostart_priority: 'P1',
    slack_notification_channel: null,
    slack_notification_min_priority: null,
}
