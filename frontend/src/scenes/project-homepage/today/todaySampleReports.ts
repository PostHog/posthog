import type { SignalNode } from 'scenes/debug/signals/types'

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
    suggestedPrompts?: string[]
    signals: {
        sourceProduct: SignalNode['source_product']
        sourceType: SignalNode['source_type']
        content: string
        hoursAgo: number
    }[]
}

// The Hedgebox demo scenarios from the Today mock, all invented. Signals leave `extra` empty so they render as
// plain cards and fetch nothing. Evidence from a product that has no signal type keeps its name in the text.
const SAMPLE_SPECS: SampleReportSpec[] = [
    {
        id: `${SAMPLE_ID_PREFIX}pr`,
        title: 'Review PR #9123',
        summary:
            '**The Safari checkout fix is ready for review.**\n\nTuesday’s deploy stopped some Safari users before payment. The checkout sent an empty billing address to the payment service.\n\nPR #9123 restores the address before payment is submitted. The change is small, tested, and ready for you.',
        hoursAgo: 2,
        priority: 'P1',
        actionability: 'immediately_actionable',
        status: SignalReportStatus.READY,
        sourceProducts: ['error_tracking', 'session_replay', 'analytics', 'github'],
        pullRequestUrl: 'https://github.com/example/hedgebox/pull/9123',
        signals: [
            {
                sourceProduct: 'error_tracking',
                sourceType: 'issue',
                content: '1,284 events. The same TypeError started after deploy #4821.',
                hoursAgo: 2,
            },
            {
                sourceProduct: 'session_replay',
                sourceType: 'session_problem',
                content: '38 recordings. Safari users stop after they submit payment.',
                hoursAgo: 3,
            },
            {
                sourceProduct: 'analytics',
                sourceType: 'anomaly_investigation',
                content: '−12 points. Safari completion fell while Chrome stayed flat.',
                hoursAgo: 4,
            },
            {
                sourceProduct: 'github',
                sourceType: 'issue',
                content: 'PR #9123. The fix restores the missing billing address.',
                hoursAgo: 5,
            },
        ],
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
        signals: [
            {
                sourceProduct: 'analytics',
                sourceType: 'anomaly_investigation',
                content: 'Experiments · 95% likely. The one-page version is the likely winner.',
                hoursAgo: 3,
            },
            {
                sourceProduct: 'analytics',
                sourceType: 'anomaly_investigation',
                content: '+6.4%. Checkout completion rose from 54.1% to 57.6%.',
                hoursAgo: 4,
            },
            {
                sourceProduct: 'session_replay',
                sourceType: 'session_problem',
                content: 'Fewer exits. People no longer pause between address and payment.',
                hoursAgo: 5,
            },
            {
                sourceProduct: 'analytics',
                sourceType: 'anomaly_investigation',
                content: 'Feature flags · Ready. The winning variant can reach everyone now.',
                hoursAgo: 6,
            },
        ],
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
        signals: [
            {
                sourceProduct: 'session_replay',
                sourceType: 'session_problem',
                content: '38 sessions. Every sampled session stalls after payment.',
                hoursAgo: 5,
            },
            {
                sourceProduct: 'analytics',
                sourceType: 'anomaly_investigation',
                content: '49% complete. Safari trails Chrome by 13 points.',
                hoursAgo: 6,
            },
            {
                sourceProduct: 'error_tracking',
                sourceType: 'issue',
                content: 'address.ts:42. The billing address is empty at submission.',
                hoursAgo: 7,
            },
            {
                sourceProduct: 'analytics',
                sourceType: 'anomaly_investigation',
                content: 'Data warehouse · Safari 17. Older Safari versions stay near their baseline.',
                hoursAgo: 8,
            },
        ],
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
        signals: [
            {
                sourceProduct: 'error_tracking',
                sourceType: 'issue',
                content: '1,284 events. TypeError in formatAddress at address.ts:42.',
                hoursAgo: 7,
            },
            {
                sourceProduct: 'analytics',
                sourceType: 'anomaly_investigation',
                content: '412 users. Most affected users arrived from Safari.',
                hoursAgo: 8,
            },
            {
                sourceProduct: 'session_replay',
                sourceType: 'session_problem',
                content: '19 sampled. The submit button stops after one click.',
                hoursAgo: 9,
            },
            {
                sourceProduct: 'analytics',
                sourceType: 'anomaly_investigation',
                content: 'Data warehouse · Deploy #4821. The first event arrived six minutes after release.',
                hoursAgo: 10,
            },
        ],
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
        signals: [
            {
                sourceProduct: 'llm_analytics',
                sourceType: 'evaluation',
                content: '+31% cost. Cost rose while the number of summaries stayed flat.',
                hoursAgo: 9,
            },
            {
                sourceProduct: 'llm_analytics',
                sourceType: 'evaluation',
                content: 'Tracing · 2.4× tokens. The new prompt repeats the source document.',
                hoursAgo: 10,
            },
            {
                sourceProduct: 'analytics',
                sourceType: 'anomaly_investigation',
                content: 'Usage flat. The same number of people used summaries.',
                hoursAgo: 11,
            },
            {
                sourceProduct: 'analytics',
                sourceType: 'anomaly_investigation',
                content: 'Data warehouse · summarize-doc. One workflow accounts for 84% of the increase.',
                hoursAgo: 12,
            },
        ],
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
        signals: [
            {
                sourceProduct: 'conversations',
                sourceType: 'feedback',
                content: 'Surveys · NPS 32. Twenty-three of 61 detractors mention pricing.',
                hoursAgo: 20,
            },
            {
                sourceProduct: 'analytics',
                sourceType: 'anomaly_investigation',
                content: 'Customer analytics · Small teams. Growing teams express the most uncertainty.',
                hoursAgo: 21,
            },
            {
                sourceProduct: 'analytics',
                sourceType: 'anomaly_investigation',
                content: '71% visited. Most detractors saw the new pricing page.',
                hoursAgo: 22,
            },
            {
                sourceProduct: 'session_replay',
                sourceType: 'session_problem',
                content: '3 comparisons. People revisit the usage table before leaving.',
                hoursAgo: 23,
            },
        ],
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
        signals: [
            {
                sourceProduct: 'analytics',
                sourceType: 'anomaly_investigation',
                content: '−13 points. Safari trails the other browsers at checkout.',
                hoursAgo: 26,
            },
            {
                sourceProduct: 'session_replay',
                sourceType: 'session_problem',
                content: '38 sessions. The same payment stall appears across sampled sessions.',
                hoursAgo: 27,
            },
            {
                sourceProduct: 'error_tracking',
                sourceType: 'issue',
                content: '1,284 events. The error appears mainly in Safari 17.',
                hoursAgo: 28,
            },
            {
                sourceProduct: 'analytics',
                sourceType: 'anomaly_investigation',
                content: 'Data warehouse · 3 browsers. Chrome and Firefox stay near their baseline.',
                hoursAgo: 29,
            },
        ],
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
        signals: [
            {
                sourceProduct: 'analytics',
                sourceType: 'anomaly_investigation',
                content: 'Experiments · 4 passed. Every release guardrail stayed within range.',
                hoursAgo: 30,
            },
            {
                sourceProduct: 'analytics',
                sourceType: 'anomaly_investigation',
                content: '+6.4%. Checkout completion improved for the winning variant.',
                hoursAgo: 31,
            },
            {
                sourceProduct: 'error_tracking',
                sourceType: 'issue',
                content: 'No increase. Payment and checkout errors stayed flat.',
                hoursAgo: 32,
            },
            {
                sourceProduct: 'conversations',
                sourceType: 'feedback',
                content: 'Surveys · Support flat. The new flow did not increase support requests.',
                hoursAgo: 33,
            },
        ],
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
        signals: [
            {
                sourceProduct: 'llm_analytics',
                sourceType: 'evaluation',
                content: 'Tracing · 24 traces. Each sampled trace contains the source text twice.',
                hoursAgo: 40,
            },
            {
                sourceProduct: 'llm_analytics',
                sourceType: 'evaluation',
                content: '2.4× tokens. Input tokens rose after the model change.',
                hoursAgo: 41,
            },
            {
                sourceProduct: 'analytics',
                sourceType: 'anomaly_investigation',
                content: 'Usage flat. Traffic did not cause the higher cost.',
                hoursAgo: 42,
            },
            {
                sourceProduct: 'analytics',
                sourceType: 'anomaly_investigation',
                content: 'Data warehouse · Quality flat. The quality score did not improve.',
                hoursAgo: 43,
            },
        ],
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
        count: SAMPLE_SPECS.length,
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
