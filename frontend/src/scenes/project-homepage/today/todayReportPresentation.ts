import { dayjs } from 'lib/dayjs'
import { colonDelimitedDuration, reverseColonDelimitedDuration } from 'lib/utils/durations'
import { isObject } from 'lib/utils/guards'
import { urls } from 'scenes/urls'

import type { ReportMetricApi, SignalNodeApi } from 'products/signals/frontend/generated/api.schemas'
import { selectReportCardImpactMetric } from 'products/signals/frontend/inbox/components/cards/ReportCardImpactMetric'
import { SignalReport } from 'products/signals/frontend/inbox/types'
import { reportMetricRowParts, reportMetricWindowLabel } from 'products/signals/frontend/inbox/utils/reportMetrics'
import { parseReportSummary } from 'products/signals/frontend/inbox/utils/reportSummary'
import { conversationsTicketUrl, genericSignalLink } from 'products/signals/frontend/inbox/utils/signalLinks'

export interface TodayReportImpact {
    metric: ReportMetricApi
    value: string
    text: string
}

export interface TodayReportSections {
    lead: string
    proposal: string | null
    expected: string | null
}

export type TodaySignalDestination =
    | { kind: 'recording'; sessionId: string; timestamp: number | null; offset: string | null }
    | { kind: 'link'; to: string; external: boolean; label: string }
    | { kind: 'read' }

export interface TodaySignalGroup {
    source: string
    signals: SignalNodeApi[]
    buckets: number[]
}

const PARAGRAPH_HEADING = /^\*\*([^*\n]+?):?\*\*:?\s*$/
const PROPOSAL_HEADINGS = new Set([
    'solution',
    'the solution',
    'fix',
    'the fix',
    'proposed fix',
    'recommended fix',
    'smallest fix',
    'recommendation',
    'recommendations',
    'recommended next step',
    'recommended next steps',
    'next step',
    'next steps',
])
const EXPECTED_HEADINGS = new Set(['expected impact', 'expected behavior', 'expected result'])
const CHART_REFERENCE = /\[([^\]]+)\]\(chart:[^)]*\)/g
const BOILERPLATE_LINES = [
    /^new error tracking issue created\b/i,
    /^this error tracking issue is experiencing a spike\b/i,
    /^\(baseline:/i,
    /^-{3,}$/,
    /^(exception|uuid|commit sha|feature|type|value|filename):/i,
]
const COUNT_NOUNS = new Set(['users', 'people', 'persons', 'sessions', 'events', 'requests', 'errors', 'share'])
const TIMELINE_BUCKETS = 14
const MIN_TIMELINE_SIGNALS = 4

function withoutChartReferences(markdown: string): string {
    return markdown.replace(CHART_REFERENCE, '$1').trim()
}

function firstParagraph(markdown: string): string {
    return markdown.split(/\n\s*\n/)[0]?.trim() ?? ''
}

function splitParagraphHeadings(markdown: string): { lead: string; sections: Map<string, string> } {
    const lines = new Map<string, string[]>()
    const leadLines: string[] = []
    let current = leadLines
    for (const line of markdown.split('\n')) {
        const heading = line.trim().match(PARAGRAPH_HEADING)
        if (heading) {
            current = []
            lines.set(heading[1].trim().toLowerCase(), current)
            continue
        }
        current.push(line)
    }
    const sections = new Map([...lines].map(([heading, body]) => [heading, body.join('\n').trim()]))
    return { lead: leadLines.join('\n').trim(), sections }
}

function pick(sections: Map<string, string>, names: Set<string>): string | null {
    for (const [heading, body] of sections) {
        if (names.has(heading) && body) {
            return body
        }
    }
    return null
}

export function todayReportSections(summary: string | null | undefined): TodayReportSections {
    const parsed = parseReportSummary(summary)
    if (parsed.sections.length > 0) {
        const proposal = parsed.sections.find((section) => section.kind === 'solution')?.body ?? null
        const expected = parsed.sections.find((section) => section.kind === 'expected-impact')?.body ?? null
        return {
            lead: withoutChartReferences(firstParagraph(parsed.lead)),
            proposal: proposal ? withoutChartReferences(proposal) : null,
            expected: expected ? withoutChartReferences(expected) : null,
        }
    }
    const { lead, sections } = splitParagraphHeadings(parsed.lead)
    const proposal = pick(sections, PROPOSAL_HEADINGS)
    const expected = pick(sections, EXPECTED_HEADINGS)
    return {
        lead: withoutChartReferences(firstParagraph(lead)),
        proposal: proposal ? withoutChartReferences(proposal) : null,
        expected: expected ? withoutChartReferences(expected) : null,
    }
}

function lowerFirst(text: string): string {
    return /^[A-Z][a-z]/.test(text) ? text.charAt(0).toLowerCase() + text.slice(1) : text
}

export function todayReportImpact(report: Pick<SignalReport, 'metrics'>): TodayReportImpact | null {
    const metric = selectReportCardImpactMetric(report.metrics)
    const parts = metric ? reportMetricRowParts(metric, metric.value) : null
    if (!metric || !parts) {
        return null
    }
    const title = metric.title.trim().replace(/\.$/, '')
    const unit = parts.unit.trim()
    const firstWord = title.split(/\s/)[0].toLowerCase()
    const named = COUNT_NOUNS.has(firstWord) || firstWord === unit.toLowerCase().split(' ')[0]
    const window = reportMetricWindowLabel(metric.query)
    const sentence = named ? lowerFirst(title) : unit ? `${unit} · ${title}` : title
    return {
        metric,
        value: parts.value,
        text: window ? `${sentence}, ${lowerFirst(window)}` : sentence,
    }
}

function plainLine(line: string): string {
    return line
        .replace(/^C:\s*/, '')
        .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
        .replace(/[`*]/g, '')
        .replace(/\\([.#()[\]_*-])/g, '$1')
        .replace(/\s+/g, ' ')
        .trim()
}

function firstSentence(text: string): string {
    const match = text.match(/^(.{40,}?[.!?])\s+[A-Z“"(]/)
    return match ? match[1] : text
}

export function signalHeadline(signal: Pick<SignalNodeApi, 'content'>): string {
    const withoutCode = signal.content.replace(/```[\s\S]*?(```|$)/g, '\n')
    for (const raw of withoutCode.split('\n')) {
        const line = plainLine(raw)
        if (!line || BOILERPLATE_LINES.some((pattern) => pattern.test(line))) {
            continue
        }
        return firstSentence(line)
    }
    return plainLine(signal.content) || 'Signal'
}

function recordingOffsetSeconds(extra: Record<string, unknown>): number | null {
    if (typeof extra.start_time === 'number' && Number.isFinite(extra.start_time)) {
        return extra.start_time
    }
    if (typeof extra.start_time === 'string') {
        return reverseColonDelimitedDuration(extra.start_time)
    }
    return null
}

function recordingStart(extra: Record<string, unknown>): string | null {
    const value = extra.recording_start_time ?? extra.session_start_time
    return typeof value === 'string' ? value : null
}

export function signalDestination(
    signal: Pick<SignalNodeApi, 'source_product' | 'source_id' | 'extra'>
): TodaySignalDestination {
    const extra = isObject(signal.extra) ? (signal.extra as Record<string, unknown>) : {}
    if (
        (signal.source_product === 'replay_vision' || signal.source_product === 'session_replay') &&
        typeof extra.session_id === 'string' &&
        extra.session_id
    ) {
        const offset = recordingOffsetSeconds(extra)
        const start = recordingStart(extra)
        return {
            kind: 'recording',
            sessionId: extra.session_id,
            timestamp: offset !== null && start ? dayjs(start).add(offset, 'second').valueOf() : null,
            offset: offset !== null ? colonDelimitedDuration(offset, 2) : null,
        }
    }
    if (signal.source_product === 'error_tracking' && signal.source_id) {
        const fingerprint = typeof extra.fingerprint === 'string' ? extra.fingerprint : undefined
        return {
            kind: 'link',
            to: urls.errorTrackingIssue(signal.source_id, fingerprint ? { fingerprint } : {}),
            external: false,
            label: 'Open issue',
        }
    }
    if (signal.source_product === 'conversations') {
        const to = conversationsTicketUrl({ source_id: signal.source_id, extra: signal.extra })
        if (to) {
            return { kind: 'link', to, external: false, label: 'Open ticket' }
        }
    }
    const link = genericSignalLink({ source_product: signal.source_product, source_id: signal.source_id, extra })
    return link ? { kind: 'link', to: link.to, external: link.external, label: 'Open' } : { kind: 'read' }
}

function timelineBuckets(signals: SignalNodeApi[], start: number, end: number): number[] {
    const buckets = new Array<number>(TIMELINE_BUCKETS).fill(0)
    const span = Math.max(end - start, 1)
    for (const signal of signals) {
        const position = (new Date(signal.timestamp).getTime() - start) / span
        buckets[Math.min(TIMELINE_BUCKETS - 1, Math.max(0, Math.floor(position * TIMELINE_BUCKETS)))] += 1
    }
    return buckets
}

export function groupSignals(signals: SignalNodeApi[]): TodaySignalGroup[] {
    const times = signals.map((signal) => new Date(signal.timestamp).getTime()).filter(Number.isFinite)
    const end = times.length ? Math.max(...times) : 0
    const start = times.length ? Math.min(Math.min(...times), end - 13 * 24 * 60 * 60 * 1000) : 0
    const bySource = new Map<string, SignalNodeApi[]>()
    for (const signal of signals) {
        bySource.set(signal.source_product, [...(bySource.get(signal.source_product) ?? []), signal])
    }
    return [...bySource.entries()]
        .map(([source, sourceSignals]) => {
            const buckets = timelineBuckets(sourceSignals, start, end)
            const spread = buckets.filter((count) => count > 0).length
            return {
                source,
                signals: sourceSignals,
                buckets: sourceSignals.length >= MIN_TIMELINE_SIGNALS && spread >= 2 ? buckets : [],
            }
        })
        .sort((first, second) => second.signals.length - first.signals.length)
}
