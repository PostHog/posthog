import { parseAccountContext, parseContextSource, summarizeContext } from './accountContextData'

const COLUMNS = [
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
]

function row(values: Record<string, unknown>): unknown[] {
    return COLUMNS.map((column) => values[column] ?? null)
}

const PLAN_FACT = 'The team plans a dashboard review next quarter.'

const RESPONSE = {
    name: 'account-context',
    columns: COLUMNS,
    results: [
        row({ section: 'meta', id: 'contract', expired_facts: 2 }),
        row({
            section: 'fact',
            id: 'fact-plan',
            author: 'ada@example.com',
            fact_text: PLAN_FACT,
            confidence: 'confirmed',
            review_due: 0,
            fact_source: 'session',
            valid_from: '2026-10-02',
        }),
        row({
            section: 'fact',
            id: 'fact-sampling',
            author: 'bo@example.com',
            fact_text: 'Recording sampling dropped to a quarter.',
            confidence: 'inferred',
            review_due: 1,
            fact_source: 'gong',
            valid_from: '',
            created_at: '2026-11-03 10:00:00',
        }),
        row({
            section: 'signal',
            id: 'signal-usage',
            signal_type: 'usage_spike',
            direction: 'up',
            signal_state: 'open',
            onset: '2026-11-01',
            change: 0.61,
            arr_at_stake: 62000,
        }),
        row({
            section: 'signal',
            id: 'signal-spend',
            signal_type: 'mrr_change',
            direction: 'up',
            signal_state: 'closed',
            onset: '2026-09-01',
            closed_on: '2026-10-20',
            change: 19,
        }),
        row({
            section: 'signal',
            id: 'signal-drop',
            signal_type: 'usage_drop',
            direction: 'down',
            signal_state: 'closed',
            onset: '2026-08-01',
            closed_on: '2026-08-20',
            change: -1,
        }),
        row({
            section: 'slack',
            id: 'https://example.slack.com/archives/C1/p1',
            summary: 'Asked about flag limits',
            observed_on: '2026-11-04',
        }),
        row({ section: 'node', id: 'subject:engagement', node_kind: 'subject', node_name: 'Engagement' }),
        row({ section: 'node', id: 'product:replay', node_kind: 'product', node_name: 'Session replay' }),
        row({ section: 'link', id: 'fact-plan', to_id: 'subject:engagement', relation: 'about' }),
        row({ section: 'link', id: 'fact-plan', to_id: 'product:replay', relation: 'about' }),
        row({ section: 'link', id: 'signal-usage', to_id: 'product:replay', relation: 'on' }),
        row({ section: 'link', id: 'signal-drop', to_id: 'product:replay', relation: 'on' }),
        row({
            section: 'link',
            id: 'signal-usage',
            to_id: 'fact-sampling',
            relation: 'explains',
            link_source: 'explain',
        }),
        row({
            section: 'link',
            id: 'signal-usage',
            to_id: 'fact-plan',
            relation: 'explains',
            link_source: 'distiller',
        }),
    ],
}

describe('accountContextData', () => {
    it('turns endpoint rows into readable facts, signals and threads', () => {
        const context = parseAccountContext(RESPONSE)

        expect(context.facts.map((fact) => fact.id)).toEqual(['fact-sampling', 'fact-plan'])
        expect(context.facts[1]).toMatchObject({
            author: 'ada',
            source: 'Agent session',
            topics: ['Session replay', 'Engagement'],
        })
        expect(context.facts[0]).toMatchObject({ source: 'Gong call', capturedOn: '2026-11-03', needsRecheck: true })
        expect(context.signals[0]).toMatchObject({
            title: 'Session replay usage up 61%',
            open: true,
            reason: { text: PLAN_FACT, likely: false },
        })
        expect(context.signals[1]).toMatchObject({ title: 'Spend up 20x', open: false, reason: null })
        expect(context.signals[2].title).toBe('Session replay usage down 100%')
        expect(context.threads[0].url).toBe('https://example.slack.com/archives/C1/p1')
        expect(context.expiredFacts).toBe(2)

        expect(summarizeContext(context)).toEqual({
            factCount: 2,
            inferredCount: 1,
            lastCapturedOn: '2026-11-03',
            writerCount: 2,
            openSignalCount: 1,
            unexplainedSignalCount: 0,
            recheckCount: 1,
        })
    })

    it('accepts a context source only when every field is present', () => {
        expect(parseContextSource({ project_id: 42, endpoint: 'account-context', account_variable: 'org' })).toEqual({
            projectId: '42',
            endpoint: 'account-context',
            accountVariable: 'org',
        })
        expect(parseContextSource({ project_id: 42, endpoint: 'account-context' })).toBeNull()
        expect(parseContextSource(true)).toBeNull()
    })
})
