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
        priority_explanation:
            'Affects 47 users on a core onboarding path, with a clean low-risk fix — high impact relative to effort.',
        actionability_explanation:
            'The 500 traces to an unchecked recipient email in the invite serializer; guarding it is a self-contained change.',
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
        priority_explanation:
            'Directly blocks revenue: 118 users hit checkout timeouts during paid upgrades, concentrated in peak traffic.',
        actionability_explanation:
            'The timeout is in payment-session creation; adding a retry and raising the client timeout is a bounded code change.',
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
        priority_explanation:
            'Moderate reach (23 users) and degrades a sharing flow, but there is a manual download workaround.',
        actionability_explanation:
            'Renderer failures point to several possible causes (file size, fonts, worker limits); needs a product call on which to fix first.',
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
    ]
    return { results, count: results.length }
}

export function mockReportTasks(reportId: string): { results: any[]; count: number; next: null; previous: null } {
    return {
        results: [
            {
                id: `${reportId}-t1`,
                relationship: 'research',
                task_id: `${reportId}-task-research`,
                created_at: BASE_DATE,
            },
            {
                id: `${reportId}-t2`,
                relationship: 'implementation',
                task_id: `${reportId}-task-impl`,
                created_at: BASE_DATE,
            },
        ],
        count: 2,
        next: null,
        previous: null,
    }
}

export function mockTask(taskId: string): any {
    const failed = taskId.includes('research')
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
        latest_run: {
            id: `${taskId}-run`,
            task: taskId,
            stage: null,
            branch: 'inbox/fix-invites',
            status: failed ? 'completed' : 'in_progress',
            environment: 'cloud',
            log_url: null,
            error_message: null,
            output: taskId.includes('impl') ? { pr_url: 'https://github.com/PostHog/posthog/pull/12001' } : {},
            state: {},
            artifacts: [],
            created_at: BASE_DATE,
            updated_at: BASE_DATE,
            completed_at: failed ? BASE_DATE : null,
        },
        created_at: BASE_DATE,
        updated_at: BASE_DATE,
        created_by: null,
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
