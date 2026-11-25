import type { DataColorToken } from 'lib/colors'
import { dayjs } from 'lib/dayjs'
import { hashCodeForString } from 'lib/utils/strings'

import type { EndpointRunResponseApi } from 'products/endpoints/frontend/generated/api.schemas'

export interface AccountContextSource {
    projectId: string
    endpoint: string
    accountVariable: string
}

export interface AccountContextFact {
    id: string
    text: string
    confirmed: boolean
    author: string
    source: string
    capturedOn: string
    needsRecheck: boolean
    topics: string[]
}

export interface AccountContextReason {
    text: string
    likely: boolean
}

export interface AccountContextSignal {
    id: string
    title: string
    open: boolean
    scheduled: boolean
    onset: string
    closedOn: string
    openDays: number | null
    arrAtStake: number | null
    reason: AccountContextReason | null
    notes: string[]
}

export interface AccountContextThread {
    url: string
    summary: string
    observedOn: string
}

export interface AccountContext {
    facts: AccountContextFact[]
    signals: AccountContextSignal[]
    threads: AccountContextThread[]
    expiredFacts: number
    truncated: boolean
}

export type FactConfidence = 'confirmed' | 'inferred'

export interface FactFilters {
    confidence: FactConfidence
    search: string
    topic: string | null
    author: string | null
    source: string | null
    recheckOnly: boolean
}

type Row = Record<string, unknown>

export const CONTEXT_COLUMNS = [
    'section',
    'id',
    'author',
    'fact_text',
    'confidence',
    'review_due',
    'fact_source',
    'valid_from',
    'created_at',
    'signal_type',
    'direction',
    'signal_state',
    'onset',
    'closed_on',
    'change',
    'arr_at_stake',
    'summary',
    'observed_on',
    'node_kind',
    'node_name',
    'to_id',
    'relation',
    'link_source',
    'expired_facts',
] as const

const SOURCE_LABELS: Record<string, string> = {
    session: 'Agent session',
    'cloud-task': 'Cloud task',
    import: 'Import',
    manual: 'Added by hand',
    gong: 'Gong call',
}

interface TitleParts {
    subject: string
    product: string | null
    amount: string
    down: boolean
}

const SIGNAL_TITLES: Record<string, (parts: TitleParts) => string> = {
    usage_spike: (p) => `${p.subject} usage up${p.amount}`,
    usage_drop: (p) => `${p.subject} usage down${p.amount}`,
    product_silent: (p) => `${p.subject} usage stopped`,
    product_new: (p) => `Started using ${p.subject}`,
    cap_hit: (p) => (p.product ? `Billing limit hit on ${p.product}` : 'Billing limit hit'),
    mrr_change: (p) => `Spend ${p.down ? 'down' : 'up'}${p.amount}`,
    arr_threshold: (p) => (p.down ? 'ARR fell below $20k' : 'ARR rose above $20k'),
    credit_runway: () => 'Prepaid credit at risk',
    renewal_window: () => 'Renewal coming up',
    cost_cut_request: () => 'Asked to cut cost',
    alternative_evaluated: () => 'Evaluating an alternative',
    champion_change: () => 'Champion changed',
}

const SCHEDULED_SIGNALS = new Set(['renewal_window', 'credit_runway'])

const TOPIC_COLOR_COUNT = 15

function text(value: unknown): string {
    return typeof value === 'string' ? value : ''
}

function amount(value: unknown): number | null {
    return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function sentenceCase(value: string): string {
    const words = value.replace(/_/g, ' ').trim()
    return words ? words[0].toUpperCase() + words.slice(1) : 'Signal'
}

function changeLabel(change: number | null): string {
    if (change === null) {
        return ''
    }
    return change >= 1
        ? ` ${Math.round((1 + change) * 10) / 10}x`
        : ` ${Math.min(100, Math.round(Math.abs(change) * 100))}%`
}

export function parseContextSource(payload: unknown): AccountContextSource | null {
    if (!payload || typeof payload !== 'object') {
        return null
    }
    const { project_id, endpoint, account_variable } = payload as Row
    const projectId = typeof project_id === 'number' ? String(project_id) : text(project_id)
    if (!projectId || !text(endpoint) || !text(account_variable)) {
        return null
    }
    return { projectId, endpoint: text(endpoint), accountVariable: text(account_variable) }
}

export function topicColor(topic: string): DataColorToken {
    return `preset-${(hashCodeForString(topic) % TOPIC_COLOR_COUNT) + 1}` as DataColorToken
}

export function sourceLabel(source: string): string {
    return SOURCE_LABELS[source] ?? ''
}

export function authorLabel(author: string): string {
    return author.split('@')[0]
}

export function signalTitle(type: string, direction: string, change: number | null, product: string | null): string {
    const title = SIGNAL_TITLES[type]
    if (!title) {
        return sentenceCase(type)
    }
    return title({ subject: product ?? 'Product', product, amount: changeLabel(change), down: direction === 'down' })
}

function signalDate(signal: AccountContextSignal): string {
    return signal.open ? signal.onset : signal.closedOn
}

function signalReason(signalLinks: Row[], factText: Map<string, string>): AccountContextReason | null {
    const reasons = signalLinks.filter((link) => link.relation === 'explains' && factText.has(text(link.to_id)))
    const reason = reasons.find((link) => link.link_source === 'distiller') ?? reasons[0]
    if (!reason) {
        return null
    }
    return { text: factText.get(text(reason.to_id)) ?? '', likely: reason.link_source !== 'distiller' }
}

function signalNotes(signalLinks: Row[], factText: Map<string, string>, reason: AccountContextReason | null): string[] {
    const notes = signalLinks
        .filter((link) => link.relation === 'acts_on')
        .map((link) => factText.get(text(link.to_id)) ?? '')
        .filter((note) => note && note !== reason?.text)
    return [...new Set(notes)]
}

function openDays(onset: string, closedOn: string): number | null {
    if (!onset || !closedOn) {
        return null
    }
    const start = dayjs.utc(onset.slice(0, 10))
    const end = dayjs.utc(closedOn.slice(0, 10))
    return start.isValid() && end.isValid() ? Math.max(0, end.diff(start, 'day')) : null
}

export function missingContextColumns(response: EndpointRunResponseApi): string[] {
    const columns = new Set(response.columns ?? [])
    return CONTEXT_COLUMNS.filter((column) => !columns.has(column))
}

function toRows(response: EndpointRunResponseApi): Row[] {
    const columns = response.columns ?? []
    return (response.results ?? []).map((values) => {
        const cells = Array.isArray(values) ? values : []
        return Object.fromEntries(columns.map((column, index) => [column, cells[index]]))
    })
}

export function parseAccountContext(response: EndpointRunResponseApi): AccountContext {
    const rows = toRows(response)
    const bySection = (section: string): Row[] => rows.filter((row) => row.section === section)

    const nodes = new Map(bySection('node').map((row) => [text(row.id), row]))
    const nodeName = (id: string): string | null => text(nodes.get(id)?.node_name) || null
    const links = bySection('link')

    const topicsByFact = new Map<string, string[]>()
    for (const link of links.filter((row) => row.relation === 'about')) {
        const node = nodes.get(text(link.to_id))
        if (!node) {
            continue
        }
        const factId = text(link.id)
        const topics = topicsByFact.get(factId) ?? []
        const name = text(node.node_name)
        if (name && !topics.includes(name)) {
            topics[node.node_kind === 'subject' ? 'push' : 'unshift'](name)
        }
        topicsByFact.set(factId, topics)
    }

    const facts: AccountContextFact[] = bySection('fact')
        .map((row) => ({
            id: text(row.id),
            text: text(row.fact_text),
            confirmed: row.confidence === 'confirmed',
            author: authorLabel(text(row.author)),
            source: sourceLabel(text(row.fact_source)),
            capturedOn: text(row.valid_from).slice(0, 10) || text(row.created_at).slice(0, 10),
            needsRecheck: amount(row.review_due) === 1,
            topics: topicsByFact.get(text(row.id)) ?? [],
        }))
        .sort((a, b) => b.capturedOn.localeCompare(a.capturedOn))

    const factText = new Map(facts.map((fact) => [fact.id, fact.text]))

    const signals: AccountContextSignal[] = bySection('signal')
        .map((row) => {
            const id = text(row.id)
            const signalLinks = links.filter((link) => text(link.id) === id)
            const product = signalLinks
                .filter((link) => link.relation === 'on')
                .map((link) => nodeName(text(link.to_id)))
                .find((name): name is string => name !== null)
            const reason = signalReason(signalLinks, factText)
            const open = row.signal_state === 'open'
            const onset = text(row.onset)
            const closedOn = text(row.closed_on)
            return {
                id,
                title: signalTitle(text(row.signal_type), text(row.direction), amount(row.change), product ?? null),
                open,
                scheduled: SCHEDULED_SIGNALS.has(text(row.signal_type)),
                onset,
                closedOn,
                openDays: open ? null : openDays(onset, closedOn),
                arrAtStake: amount(row.arr_at_stake),
                reason,
                notes: signalNotes(signalLinks, factText, reason),
            }
        })
        .sort((a, b) => signalDate(b).localeCompare(signalDate(a)))

    const threads: AccountContextThread[] = bySection('slack')
        .map((row) => ({ url: text(row.id), summary: text(row.summary), observedOn: text(row.observed_on) }))
        .sort((a, b) => b.observedOn.localeCompare(a.observedOn))

    const meta = bySection('meta')[0]
    return {
        facts,
        signals,
        threads,
        expiredFacts: amount(meta?.expired_facts) ?? 0,
        truncated: response.hasMore === true,
    }
}

export function filterFacts(facts: AccountContextFact[], filters: FactFilters): AccountContextFact[] {
    const search = filters.search.trim().toLowerCase()
    const checks: ((fact: AccountContextFact) => boolean)[] = [
        (fact) => fact.confirmed === (filters.confidence === 'confirmed'),
    ]
    if (search) {
        checks.push((fact) => fact.text.toLowerCase().includes(search))
    }
    if (filters.topic) {
        checks.push((fact) => fact.topics.includes(filters.topic as string))
    }
    if (filters.author) {
        checks.push((fact) => fact.author === filters.author)
    }
    if (filters.source) {
        checks.push((fact) => fact.source === filters.source)
    }
    if (filters.recheckOnly) {
        checks.push((fact) => fact.needsRecheck)
    }
    return facts.filter((fact) => checks.every((check) => check(fact)))
}

export function factFilterOptions(facts: AccountContextFact[]): {
    topics: string[]
    authors: string[]
    sources: string[]
} {
    const distinct = (values: string[]): string[] => [...new Set(values.filter(Boolean))].sort()
    return {
        topics: distinct(facts.flatMap((fact) => fact.topics)),
        authors: distinct(facts.map((fact) => fact.author)),
        sources: distinct(facts.map((fact) => fact.source)),
    }
}
