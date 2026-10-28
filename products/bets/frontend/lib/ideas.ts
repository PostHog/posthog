import type { BetsDetailApi, BetsEvidenceApi, BetsWorkApi, EvidenceKindEnumApi } from '../generated/api.schemas'
import { isOpen } from './workStatus'

export interface IdeaBadge {
    label: string
    variant: 'success' | 'default' | 'info'
}

const ASSESSMENT_BADGES: Record<string, IdeaBadge> = {
    supported: { label: 'Supported', variant: 'success' },
    not_supported: { label: 'Not supported', variant: 'default' },
    pending: { label: 'Checking', variant: 'info' },
    no_verdict: { label: 'No verdict', variant: 'default' },
}

const EVIDENCE_ORDER: Partial<Record<EvidenceKindEnumApi, number>> = {
    replay: 0,
    insight: 1,
    chart: 1,
    error: 2,
    experiment: 3,
}

export const SHOWN_EVIDENCE = 3

export const IDEA_ICON_COLOR = 'var(--color-product-early-access-features-light)'

const ASSESSMENT_MARKER = /^\s*(?:not supported|supported)\s*[.:]\s*/i

export function ideaAssessment(item: BetsWorkApi): string {
    return item.assessment === 'pending' && item.report_id ? 'no_verdict' : item.assessment
}

function ideaBadge(item: BetsWorkApi): IdeaBadge | null {
    return ASSESSMENT_BADGES[ideaAssessment(item)] ?? null
}

export function ideaStatus(item: BetsWorkApi): string[] {
    const badge = ideaBadge(item)
    return [item.source === 'owner' ? 'Your idea' : 'Scout idea', badge?.label ?? '']
}

export function ideaEvidence(item: BetsWorkApi): BetsEvidenceApi[] {
    return item.evidence
        .map((evidence, index) => ({ evidence, index, rank: EVIDENCE_ORDER[evidence.kind] }))
        .filter(
            (entry): entry is { evidence: BetsEvidenceApi; index: number; rank: number } => entry.rank !== undefined
        )
        .sort((a, b) => a.rank - b.rank || a.index - b.index)
        .map((entry) => entry.evidence)
}

export function firstSupportedIdea(ideas: BetsWorkApi[]): string | null {
    return ideas.find((item) => item.assessment === 'supported')?.id ?? null
}

function ideaReport(item: BetsWorkApi): string {
    return item.summary.replace(ASSESSMENT_MARKER, '').trim()
}

export function ideaReason(item: BetsWorkApi): string {
    const [first = ''] = ideaReport(item).split(/(?<=[.!?])\s+/)
    return first.trim()
}

export function ideaReportRest(item: BetsWorkApi): string {
    const report = ideaReport(item)
    const reason = ideaReason(item)
    return report.startsWith(reason) ? report.slice(reason.length).trim() : report
}

export function hasMoreReport(item: BetsWorkApi): boolean {
    return ideaReportRest(item).length > 0
}

function isCurrentIdea(item: BetsWorkApi, bet: Pick<BetsDetailApi, 'goal_version'>): boolean {
    return item.kind === 'idea' && item.goal_version === bet.goal_version
}

export function isBuilt(item: BetsWorkApi): boolean {
    return item.stage !== 'proposed' && item.stage !== 'dismissed'
}

type BetWork = Pick<BetsDetailApi, 'work' | 'goal_version'>

const ASSESSMENT_ORDER: Record<string, number> = { supported: 0, pending: 1, '': 2, not_supported: 3 }

export function waitingIdeas(bet: BetWork): BetsWorkApi[] {
    return bet.work
        .filter((item) => isCurrentIdea(item, bet) && item.stage === 'proposed')
        .map((item, index) => ({ item, index }))
        .sort((a, b) => ASSESSMENT_ORDER[a.item.assessment] - ASSESSMENT_ORDER[b.item.assessment] || a.index - b.index)
        .map(({ item }) => item)
}

export function isChecking(item: BetsWorkApi): boolean {
    return item.source === 'owner' && !item.report_id
}

export function readyIdeas(bet: BetWork): BetsWorkApi[] {
    return waitingIdeas(bet).filter((item) => !isChecking(item))
}

export function dismissedIdeas(bet: BetWork): BetsWorkApi[] {
    return bet.work.filter((item) => isCurrentIdea(item, bet) && item.stage === 'dismissed')
}

export function ideaInProgress(bet: BetWork): BetsWorkApi | null {
    return bet.work.find((item) => isCurrentIdea(item, bet) && isOpen(item)) ?? null
}

export function buildDisabledReason(bet: BetsDetailApi): string | null {
    if (ideaInProgress(bet)) {
        return "Wait for the current idea's result."
    }
    if (bet.status === 'paused') {
        return 'Resume the bet to build an idea.'
    }
    if (bet.status === 'setting_up') {
        return 'The bet is still setting up.'
    }
    if (bet.status === 'spent' || (bet.status === 'running' && bet.money.available_cents <= 0)) {
        return 'The budget is used. Back this bet to add budget.'
    }
    if (bet.status !== 'running') {
        return 'Ideas can only be built while the bet runs.'
    }
    return null
}

const IN_PROGRESS_LABELS: Record<string, string> = {
    working: 'Building',
    review: 'In review',
    live: 'Testing',
    stuck: 'Needs attention',
}

export function inProgressLabel(item: BetsWorkApi): string {
    return IN_PROGRESS_LABELS[item.stage] ?? 'Building'
}

export function laterLabel(count: number): string {
    return `${count} other ${count === 1 ? 'idea waits' : 'ideas wait'} in Later`
}

export function ideasCount(count: number): string {
    return `${count} ${count === 1 ? 'idea' : 'ideas'} ready`
}
