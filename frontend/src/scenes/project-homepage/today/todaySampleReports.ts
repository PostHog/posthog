import type { ReportMetricApi } from 'products/signals/frontend/generated/api.schemas'
import { SignalReport, SignalReportStatus } from 'products/signals/frontend/inbox/types'

import type { TodayReports } from './todayLogic'
import { TodayBriefingSegment } from './todaySignalReports'

// Sample ids carry this prefix, so a report page knows to read the fixture rather than the API.
const SAMPLE_ID_PREFIX = 'sample-'
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
    metrics?: ReportMetricApi[]
    suggestedPrompts?: string[]
    signalCount: number
}

// The Hedgebox demo scenarios from the Today mock, all invented. Signals leave `extra` empty so they render as
// plain cards and fetch nothing. Evidence from a product that has no signal type keeps its name in the text.
const SAMPLE_SPECS: SampleReportSpec[] = [
    {
        id: `${SAMPLE_ID_PREFIX}pr`,
        title: 'Review PR #9123',
        summary:
            'Safari users can’t finish checkout since Tuesday’s deploy, because the checkout sends an empty billing address to the payment service.\n\n## Problem\n\nThe deploy moved the address form into a step that Safari unmounts before payment. The payment request then goes out without the billing address.\n\n## Impact\n\nSafari checkout completion fell by 12 points while Chrome stayed flat.\n\n## Solution\n\nKeep the billing address in the checkout state, and send it with the payment request. PR #9123 does this and adds a Safari test.\n\n## Expected impact\n\nSafari checkout completion returns to **about 54%**, the same as Chrome.',
        hoursAgo: 2,
        priority: 'P1',
        actionability: 'immediately_actionable',
        status: SignalReportStatus.READY,
        sourceProducts: ['error_tracking', 'session_replay', 'analytics', 'github'],
        pullRequestUrl: 'https://github.com/example/hedgebox/pull/9123',
        metrics: [
            {
                metric_id: 'safari-checkout-failures',
                title: 'Users who could not finish checkout in Safari',
                kind: 'affected_users',
                role: 'primary',
                value: 212,
                series: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 31, 58, 64, 59],
                value_format: 'count',
                unit: 'users',
            },
        ],
        signalCount: 4,
    },
    {
        id: `${SAMPLE_ID_PREFIX}exp`,
        title: 'Ship one-page checkout',
        summary:
            '**One-page checkout won. It is safe to ship.**\n\nThe shorter checkout completed more often than the current flow. It did not increase refunds, support requests, or payment errors.\n\nThe result passed the team’s decision threshold. You can send the winning flow to everyone today.',
        hoursAgo: 3,
        priority: 'P1',
        actionability: 'immediately_actionable',
        status: SignalReportStatus.READY,
        sourceProducts: ['analytics', 'session_replay'],
        signalCount: 4,
    },
    {
        id: `${SAMPLE_ID_PREFIX}safari`,
        title: 'Watch 38 Safari recordings',
        summary:
            '**Safari users reach payment, then get stuck.**\n\nThe recordings show the same sequence. A person enters a card, submits payment, and sees no progress.\n\nThe problem affects Safari 17 after Tuesday’s deploy. Chrome sessions continue through the same step.',
        hoursAgo: 5,
        priority: 'P1',
        actionability: 'requires_human_input',
        status: SignalReportStatus.PENDING_INPUT,
        sourceProducts: ['session_replay', 'analytics', 'error_tracking'],
        signalCount: 4,
    },
    {
        id: `${SAMPLE_ID_PREFIX}error`,
        title: 'Triage the formatAddress TypeError',
        summary:
            '**One new error is blocking checkout completion.**\n\nThe error begins when checkout formats an empty billing address. It started with deploy #4821 and appears only after payment submission.\n\nFour hundred and twelve people saw it. The same error also explains the Safari conversion drop.',
        hoursAgo: 7,
        priority: 'P2',
        actionability: 'immediately_actionable',
        status: SignalReportStatus.READY,
        sourceProducts: ['error_tracking', 'analytics', 'session_replay'],
        pullRequestUrl: 'https://github.com/example/hedgebox/pull/9131',
        signalCount: 4,
    },
    {
        id: `${SAMPLE_ID_PREFIX}llm`,
        title: 'Check which model summarize-doc uses',
        summary:
            '**Document summaries became more expensive overnight.**\n\nThe summarize-doc workflow now spends 31% more per active user. Usage stayed flat, so higher traffic does not explain the change.\n\nMost of the increase comes from a model change and longer prompts. The quality score did not improve.',
        hoursAgo: 9,
        priority: 'P2',
        actionability: 'immediately_actionable',
        status: SignalReportStatus.READY,
        sourceProducts: ['llm_analytics', 'analytics'],
        pullRequestUrl: 'https://github.com/example/hedgebox/pull/9140',
        signalCount: 4,
    },
    {
        id: `${SAMPLE_ID_PREFIX}nps`,
        title: 'Read 23 pricing complaints',
        summary:
            '**Pricing is the main reason detractors hesitate.**\n\nTwenty-three detractors mention pricing in their survey response. Most of them visited the new pricing page before they replied.\n\nThey understand the product, but they cannot predict the bill. The confusion is strongest among small teams with growing data volume.',
        hoursAgo: 20,
        priority: 'P3',
        actionability: 'requires_human_input',
        status: SignalReportStatus.PENDING_INPUT,
        sourceProducts: ['conversations', 'analytics', 'session_replay'],
        signalCount: 4,
    },
    {
        id: `${SAMPLE_ID_PREFIX}browser`,
        title: 'Compare checkout by browser',
        summary:
            '**Safari accounts for the checkout gap.**\n\nChrome and Firefox remain near their usual completion rates. Safari 17 falls sharply after payment submission.\n\nThe browser comparison isolates the problem to one checkout path. Mobile Safari shows the largest drop.',
        hoursAgo: 26,
        priority: 'P3',
        actionability: 'requires_human_input',
        status: SignalReportStatus.PENDING_INPUT,
        sourceProducts: ['analytics', 'session_replay', 'error_tracking'],
        pullRequestUrl: 'https://github.com/example/hedgebox/pull/9123',
        signalCount: 4,
    },
    {
        id: `${SAMPLE_ID_PREFIX}guardrails`,
        title: 'Review experiment guardrails',
        summary:
            '**The winning checkout passed every guardrail.**\n\nThe shorter checkout increased completion without increasing refunds, support requests, or payment failures.\n\nEach guardrail stayed within its agreed range. The result is ready for a full rollout.',
        hoursAgo: 30,
        priority: 'P3',
        actionability: 'immediately_actionable',
        status: SignalReportStatus.READY,
        sourceProducts: ['analytics', 'error_tracking', 'conversations'],
        signalCount: 4,
    },
    {
        id: `${SAMPLE_ID_PREFIX}traces`,
        title: 'Check summary-model traces',
        summary:
            '**The new summary model repeats the source document.**\n\nRecent traces show the source text twice in the prompt. This duplication explains most of the token increase.\n\nThe model change did not improve the quality score. The previous model remains the lower-cost option.',
        hoursAgo: 40,
        priority: 'P3',
        actionability: 'immediately_actionable',
        status: SignalReportStatus.READY,
        sourceProducts: ['llm_analytics', 'analytics'],
        pullRequestUrl: 'https://github.com/example/hedgebox/pull/9147',
        signalCount: 4,
    },
]

const BRIEFING_LINK = (id: string, text: string, highlight?: boolean): TodayBriefingSegment => ({
    text,
    reportId: `${SAMPLE_ID_PREFIX}${id}`,
    ...(highlight ? { highlight } : {}),
})

/** The hand-written briefing from the mock, which reads better than one built from report titles. */
export const SAMPLE_BRIEFING: TodayBriefingSegment[][] = [
    [
        BRIEFING_LINK('safari', 'Safari users can’t pay'),
        { text: ' since Tuesday’s deploy, and ' },
        BRIEFING_LINK('pr', 'a fix is waiting', true),
        { text: ' for your review.' },
    ],
    [BRIEFING_LINK('exp', 'One-page checkout won'), { text: ' its experiment, and signups beat the forecast by 18%.' }],
    [
        { text: 'Keep an eye on ' },
        BRIEFING_LINK('error', 'one new error'),
        { text: ', LLM cost per user ' },
        BRIEFING_LINK('llm', 'up 31%'),
        { text: ', and ' },
        BRIEFING_LINK('nps', 'pricing that confuses people'),
        { text: '.' },
    ],
]

function buildSampleReport(spec: SampleReportSpec, now: number): SignalReport {
    const updatedAt = new Date(now - spec.hoursAgo * HOUR_MS).toISOString()
    return {
        id: spec.id,
        title: spec.title,
        summary: spec.summary,
        status: spec.status,
        total_weight: spec.signalCount,
        signal_count: spec.signalCount,
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
        metrics: spec.metrics ?? [],
    }
}

export function sampleTopReports(limit: number, now: number = Date.now()): TodayReports {
    return {
        results: SAMPLE_SPECS.slice(0, limit).map((spec) => buildSampleReport(spec, now)),
        count: SAMPLE_SPECS.length,
    }
}

export function findSampleReport(reportId: string, now: number = Date.now()): SignalReport | null {
    const spec = SAMPLE_SPECS.find((candidate) => candidate.id === reportId)
    return spec ? buildSampleReport(spec, now) : null
}
