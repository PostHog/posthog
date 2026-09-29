import type { SignalNode } from 'scenes/debug/signals/types'

import { SignalReport, SignalReportStatus } from 'products/signals/frontend/inbox/types'

import type { TodayReports } from './todayLogic'

// Sample ids carry this prefix, so a report page knows to read the fixture rather than the API.
const SAMPLE_ID_PREFIX = 'sample-'
// Pretends more reports wait in the Inbox, so the "more in the Inbox" link shows too.
const SAMPLE_TOTAL_COUNT = 8
const HOUR_MS = 60 * 60 * 1000

export function isSampleReportId(reportId: string): boolean {
    return reportId.startsWith(SAMPLE_ID_PREFIX)
}

/** `?sample=1` turns sample data on, `?sample=0` turns it off, and anything else leaves it as it is. */
export function parseSampleParam(value: unknown): boolean | null {
    const normalized = String(value ?? '').toLowerCase()
    if (['1', 'true', 'on'].includes(normalized)) {
        return true
    }
    if (['0', 'false', 'off'].includes(normalized)) {
        return false
    }
    return null
}

interface SampleReportSpec {
    id: string
    title: string
    summary: string
    hoursAgo: number
    priority: SignalReport['priority']
    actionability: SignalReport['actionability']
    status: SignalReportStatus
    sourceProducts: string[]
    pullRequestUrl?: string
    suggestedPrompts?: string[]
    signals: {
        sourceProduct: SignalNode['source_product']
        sourceType: SignalNode['source_type']
        content: string
        hoursAgo: number
    }[]
}

// Invented data for trying Home. Signals leave `extra` empty so they render as plain cards and fetch nothing.
const SAMPLE_SPECS: SampleReportSpec[] = [
    {
        id: `${SAMPLE_ID_PREFIX}signup-validation`,
        title: 'Signup form rejects email addresses with a plus sign',
        summary:
            'Since the last release, the signup form rejects any email address that contains a plus sign. People who use plus addressing see "Enter a valid email address" and cannot finish signing up.\n\n## Impact\n\nSignup completions dropped for new visitors on the pricing page path.\n\n## Solution\n\nA pull request relaxes the email check to accept plus addressing and adds a test for it.',
        hoursAgo: 2,
        priority: 'P1',
        actionability: 'immediately_actionable',
        status: SignalReportStatus.READY,
        sourceProducts: ['error_tracking', 'session_replay'],
        pullRequestUrl: 'https://github.com/example/app/pull/1234',
        signals: [
            {
                sourceProduct: 'error_tracking',
                sourceType: 'issue',
                content: 'Validation error on the signup form for an address with a plus sign.',
                hoursAgo: 3,
            },
            {
                sourceProduct: 'session_replay',
                sourceType: 'session_problem',
                content: 'A visitor submitted the signup form four times, then left the page.',
                hoursAgo: 5,
            },
        ],
    },
    {
        id: `${SAMPLE_ID_PREFIX}llm-cost`,
        title: 'LLM costs doubled for the summarize tool',
        summary:
            'Token usage for the summarize tool doubled after its prompt changed. Each call now sends the full conversation instead of the last few turns.\n\n## Impact\n\nDaily spend on this tool is about twice what it was last week, with no change in call volume.',
        hoursAgo: 6,
        priority: 'P2',
        actionability: 'immediately_actionable',
        status: SignalReportStatus.READY,
        sourceProducts: ['llm_analytics'],
        suggestedPrompts: ['Which prompt change caused the jump?', 'Draft a fix that trims the conversation history'],
        signals: [
            {
                sourceProduct: 'llm_analytics',
                sourceType: 'evaluation',
                content: 'Average input tokens per summarize call rose from about 2,000 to about 4,100.',
                hoursAgo: 7,
            },
        ],
    },
    {
        id: `${SAMPLE_ID_PREFIX}pricing-dropoff`,
        title: 'Pricing page visitors drop off at the plan table',
        summary:
            'Most visitors who scroll to the plan table leave without starting a trial. The comparison rows below the fold get almost no attention.\n\n## Open question\n\nShould the team test a shorter table, or a single recommended plan?',
        hoursAgo: 20,
        priority: 'P2',
        actionability: 'requires_human_input',
        status: SignalReportStatus.PENDING_INPUT,
        sourceProducts: ['analytics'],
        signals: [
            {
                sourceProduct: 'analytics',
                sourceType: 'anomaly_investigation',
                content: 'Trial starts from the pricing page fell week over week while pricing page views held steady.',
                hoursAgo: 22,
            },
        ],
    },
    {
        id: `${SAMPLE_ID_PREFIX}export-timeouts`,
        title: 'CSV exports time out for large dashboards',
        summary:
            'Exports of dashboards with more than twenty tiles time out after 60 seconds. The export runs each tile query in sequence.\n\n## Solution\n\nRun tile queries in parallel, or raise the export timeout for large dashboards.',
        hoursAgo: 28,
        priority: 'P3',
        actionability: 'immediately_actionable',
        status: SignalReportStatus.READY,
        sourceProducts: ['logs'],
        signals: [
            {
                sourceProduct: 'logs',
                sourceType: 'alert_state_change',
                content: 'Export worker logged a timeout while rendering a dashboard with 24 tiles.',
                hoursAgo: 30,
            },
        ],
    },
    {
        id: `${SAMPLE_ID_PREFIX}support-login`,
        title: 'Support tickets about login loops are rising',
        summary:
            'More support tickets describe being sent back to the login page right after signing in. Most mention an ad blocker or strict privacy settings.\n\n## Open question\n\nIs this the session cookie change, or a third-party script being blocked?',
        hoursAgo: 40,
        priority: 'P3',
        actionability: 'requires_human_input',
        status: SignalReportStatus.PENDING_INPUT,
        sourceProducts: ['zendesk'],
        signals: [
            {
                sourceProduct: 'zendesk',
                sourceType: 'ticket',
                content: 'Ticket: signing in sends me straight back to the login page.',
                hoursAgo: 41,
            },
        ],
    },
]

function buildSampleReport(spec: SampleReportSpec, now: number): SignalReport {
    const updatedAt = new Date(now - spec.hoursAgo * HOUR_MS).toISOString()
    return {
        id: spec.id,
        title: spec.title,
        summary: spec.summary,
        status: spec.status,
        total_weight: spec.signals.length,
        signal_count: spec.signals.length,
        created_at: updatedAt,
        updated_at: updatedAt,
        artefact_count: 0,
        is_suggested_reviewer: true,
        priority: spec.priority,
        actionability: spec.actionability,
        already_addressed: false,
        source_products: spec.sourceProducts,
        implementation_pr_url: spec.pullRequestUrl ?? null,
        suggested_prompts: spec.suggestedPrompts,
        charts: [],
    }
}

export function sampleTopReports(limit: number, now: number = Date.now()): TodayReports {
    return {
        results: SAMPLE_SPECS.slice(0, limit).map((spec) => buildSampleReport(spec, now)),
        count: SAMPLE_TOTAL_COUNT,
    }
}

export function findSampleReport(reportId: string, now: number = Date.now()): SignalReport | null {
    const spec = SAMPLE_SPECS.find((candidate) => candidate.id === reportId)
    return spec ? buildSampleReport(spec, now) : null
}

export function sampleSignals(reportId: string, now: number = Date.now()): SignalNode[] {
    const spec = SAMPLE_SPECS.find((candidate) => candidate.id === reportId)
    return (spec?.signals ?? []).map((signal, index) => ({
        signal_id: `${reportId}-signal-${index}`,
        content: signal.content,
        source_product: signal.sourceProduct,
        source_type: signal.sourceType,
        source_id: `${reportId}-source-${index}`,
        weight: 1,
        timestamp: new Date(now - signal.hoursAgo * HOUR_MS).toISOString(),
        extra: {} as SignalNode['extra'],
    }))
}
