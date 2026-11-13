import type { UncoveredGroupApi, UsageSnapshotPayloadApi } from './generated/api.schemas'
import { buildProposedRows, proposedRowPrefill } from './proposedRows'

function group(digest: string, overrides: Partial<UncoveredGroupApi> = {}): UncoveredGroupApi {
    return {
        fingerprint_digest: digest,
        measure: `measure ${digest}`,
        outcome: 'uncovered',
        matched_metric_id: null,
        distinct_people: 2,
        views: 0,
        built: 4,
        complexity: 1,
        sample_sql: `SELECT ${digest}`,
        draft_name: null,
        draft_description: null,
        draft_definition: null,
        ...overrides,
    }
}

const PROPOSAL = {
    name: 'user_signups',
    description: 'Counts signups.',
    definition: 'SELECT count() FROM events',
    measures: 2,
    people: 9,
    views: 12,
    built: 40,
    complexity: 1,
    charts: [],
    other_charts: 0,
    surfaces: [],
    agents: null,
}

const PAYLOAD: UsageSnapshotPayloadApi = {
    metric_runs: null,
    adjusted_runs: null,
    topics: null,
    topic_definitions: null,
    topic_sessions: null,
    table_sources: null,
    uncovered: [
        group('a', { draft_name: 'user_signups' }),
        group('b', { draft_name: 'user_signups' }),
        group('c', { distinct_people: 20 }),
        group('e', { draft_name: 'orphan_draft', draft_definition: 'SELECT orphan', distinct_people: 1 }),
        group('f', { outcome: 'covered', distinct_people: 30 }),
        group('g', { outcome: 'slice', matched_metric_id: 'metric-1', distinct_people: 15 }),
        group('h', { distinct_people: 0, views: 5, built: 1 }),
        group('k', { distinct_people: 1, complexity: 3 }),
    ],
    proposed_metrics: [PROPOSAL],
    failed_sections: [],
}

describe('proposedRows', () => {
    it('merges drafted measures into their proposal, leaves out covered measures and ranks complex ones first', () => {
        const rows = buildProposedRows(PAYLOAD)

        expect(rows.map((row) => [row.name ?? row.measure, row.people, row.built, row.viewed])).toEqual([
            ['measure k', 1, 4, 0],
            ['measure c', 20, 4, 0],
            ['measure g', 15, 4, 0],
            ['user_signups', 9, 40, 12],
            ['orphan_draft', 1, 4, 0],
            ['measure h', 0, 1, 5],
        ])
        expect(rows.find((row) => row.measure === 'measure g')?.matchedMetricId).toBe('metric-1')
    })

    it('shows the rows from an older scan that has no proposals section', () => {
        const rows = buildProposedRows({ ...PAYLOAD, proposed_metrics: null })

        expect(rows.map((row) => row.name ?? row.measure)).toEqual([
            'measure k',
            'measure c',
            'measure g',
            'user_signups',
            'user_signups',
            'orphan_draft',
            'measure h',
        ])
    })

    it.each([
        [
            'a draft fills the whole form',
            { ...buildProposedRows(PAYLOAD).find((row) => row.name === 'user_signups')! },
            {
                display_name: 'User signups',
                name: 'user_signups',
                description: 'Counts signups.',
                sql: 'SELECT count() FROM events',
            },
        ],
        [
            'a measure with no draft fills only the query',
            { ...buildProposedRows(PAYLOAD).find((row) => row.measure === 'measure c')! },
            { display_name: '', name: '', description: '', sql: 'SELECT c' },
        ],
    ])('prefills the new metric form: %s', (_name, row, expected) => {
        expect(proposedRowPrefill(row)).toEqual(expected)
    })
})
