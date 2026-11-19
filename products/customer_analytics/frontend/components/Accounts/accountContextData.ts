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
    onset: string
    closedOn: string
    arrAtStake: number | null
    reason: AccountContextReason | null
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
}

export interface AccountContextSummary {
    factCount: number
    inferredCount: number
    lastCapturedOn: string | null
    writerCount: number
    openSignalCount: number
    unexplainedSignalCount: number
    recheckCount: number
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

const SOURCE_LABELS: Record<string, string> = {
    session: 'Agent session',
    'cloud-task': 'Cloud task',
    import: 'Import',
    manual: 'Added by hand',
    gong: 'Gong call',
}

const FIXED_SIGNAL_TITLES: Record<string, string> = {
    credit_runway: 'Prepaid credit at risk',
    renewal_window: 'Renewal coming up',
    cost_cut_request: 'Asked to cut cost',
    alternative_evaluated: 'Evaluating an alternative',
    champion_change: 'Champion changed',
}

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

export function sourceLabel(source: string): string {
    return SOURCE_LABELS[source] ?? ''
}

export function authorLabel(author: string): string {
    return author.split('@')[0]
}

export function signalTitle(type: string, direction: string, change: number | null, product: string | null): string {
    const subject = product ?? 'Product'
    switch (type) {
        case 'usage_spike':
            return `${subject} usage up${changeLabel(change)}`
        case 'usage_drop':
            return `${subject} usage down${changeLabel(change)}`
        case 'product_silent':
            return `${subject} usage stopped`
        case 'product_new':
            return `Started using ${subject}`
        case 'cap_hit':
            return product ? `Billing limit hit on ${product}` : 'Billing limit hit'
        case 'mrr_change':
            return `Spend ${direction === 'down' ? 'down' : 'up'}${changeLabel(change)}`
        case 'arr_threshold':
            return direction === 'down' ? 'ARR fell below $20k' : 'ARR rose above $20k'
        default:
            return FIXED_SIGNAL_TITLES[type] ?? sentenceCase(type)
    }
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
            const reasons = signalLinks
                .filter((link) => link.relation === 'explains' && factText.has(text(link.to_id)))
                .sort((a) => (a.link_source === 'distiller' ? -1 : 1))
            const reason = reasons[0]
            return {
                id,
                title: signalTitle(text(row.signal_type), text(row.direction), amount(row.change), product ?? null),
                open: row.signal_state === 'open',
                onset: text(row.onset),
                closedOn: text(row.closed_on),
                arrAtStake: amount(row.arr_at_stake),
                reason: reason
                    ? { text: factText.get(text(reason.to_id)) ?? '', likely: reason.link_source !== 'distiller' }
                    : null,
            }
        })
        .sort((a, b) => b.onset.localeCompare(a.onset))

    const threads: AccountContextThread[] = bySection('slack')
        .map((row) => ({ url: text(row.id), summary: text(row.summary), observedOn: text(row.observed_on) }))
        .sort((a, b) => b.observedOn.localeCompare(a.observedOn))

    const meta = bySection('meta')[0]
    return { facts, signals, threads, expiredFacts: amount(meta?.expired_facts) ?? 0 }
}

export function summarizeContext(context: AccountContext): AccountContextSummary {
    const openSignals = context.signals.filter((signal) => signal.open)
    const captured = context.facts.map((fact) => fact.capturedOn).filter(Boolean)
    return {
        factCount: context.facts.length,
        inferredCount: context.facts.filter((fact) => !fact.confirmed).length,
        lastCapturedOn: captured.length ? captured.reduce((a, b) => (a > b ? a : b)) : null,
        writerCount: new Set(context.facts.map((fact) => fact.author).filter(Boolean)).size,
        openSignalCount: openSignals.length,
        unexplainedSignalCount: openSignals.filter((signal) => !signal.reason).length,
        recheckCount: context.facts.filter((fact) => fact.needsRecheck).length,
    }
}

export function filterFacts(facts: AccountContextFact[], filters: FactFilters): AccountContextFact[] {
    const search = filters.search.trim().toLowerCase()
    return facts.filter(
        (fact) =>
            fact.confirmed === (filters.confidence === 'confirmed') &&
            (!search || fact.text.toLowerCase().includes(search)) &&
            (!filters.topic || fact.topics.includes(filters.topic)) &&
            (!filters.author || fact.author === filters.author) &&
            (!filters.source || fact.source === filters.source) &&
            (!filters.recheckOnly || fact.needsRecheck)
    )
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
