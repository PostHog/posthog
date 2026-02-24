import { evaluateDetections, resolveFindings } from './hogSenseLogic'
import type { DetectionEntry, GroupKnowledgeEntry, KnowledgeEntry } from './types'

describe('evaluateDetections', () => {
    it('returns empty results when no entries match', () => {
        const entries: DetectionEntry<{ active: boolean }>[] = [
            { id: 'test-entry', trigger: (ctx) => ctx.active, severity: 'info' },
        ]
        expect(evaluateDetections(entries, { active: false })).toEqual([])
    })

    it('returns results for matching entries', () => {
        const entries: DetectionEntry<{ active: boolean }>[] = [
            { id: 'test-entry', trigger: (ctx) => ctx.active, severity: 'warning' },
        ]
        expect(evaluateDetections(entries, { active: true })).toEqual([
            { id: 'test-entry', severity: 'warning', entityType: undefined, entityId: undefined },
        ])
    })

    it('preserves entity metadata on results', () => {
        const entries: DetectionEntry<{ value: number }>[] = [
            { id: 'threshold', trigger: (ctx) => ctx.value > 100, severity: 'error' },
        ]
        expect(evaluateDetections(entries, { value: 200 }, { entityType: 'feature_flag', entityId: 42 })).toEqual([
            { id: 'threshold', severity: 'error', entityType: 'feature_flag', entityId: 42 },
        ])
    })

    it('returns multiple results when multiple entries match', () => {
        const entries: DetectionEntry<{ a: boolean; b: boolean }>[] = [
            { id: 'entry-a', trigger: (ctx) => ctx.a, severity: 'info' },
            { id: 'entry-b', trigger: (ctx) => ctx.b, severity: 'warning' },
            { id: 'entry-c', trigger: () => false, severity: 'error' },
        ]
        const results = evaluateDetections(entries, { a: true, b: true })
        expect(results).toHaveLength(2)
        expect(results.map((r) => r.id)).toEqual(['entry-a', 'entry-b'])
    })

    it('returns empty results for empty entries array', () => {
        expect(evaluateDetections([], {})).toEqual([])
    })
})

describe('resolveFindings', () => {
    const knowledge: Record<string, KnowledgeEntry> = {
        'known-id': {
            summary: 'Known',
            description: 'A known detection',
            docs: [{ label: 'Docs', url: 'https://example.com' }],
        },
        'another-id': { summary: 'Another', description: 'Another detection' },
    }

    it('enriches detection results with knowledge', () => {
        const results = [{ id: 'known-id', severity: 'warning' as const }]
        expect(resolveFindings(results, knowledge)).toEqual([
            {
                id: 'known-id',
                severity: 'warning',
                summary: 'Known',
                description: 'A known detection',
                docs: [{ label: 'Docs', url: 'https://example.com' }],
            },
        ])
    })

    it('filters out results without knowledge entries', () => {
        const results = [
            { id: 'known-id', severity: 'info' as const },
            { id: 'unknown-id', severity: 'error' as const },
        ]
        expect(resolveFindings(results, knowledge)).toHaveLength(1)
        expect(resolveFindings(results, knowledge)[0].id).toBe('known-id')
    })

    it('preserves entity metadata through resolution', () => {
        const results = [{ id: 'known-id', severity: 'info' as const, entityType: 'flag', entityId: 7 }]
        const findings = resolveFindings(results, knowledge)
        expect(findings[0].entityType).toBe('flag')
        expect(findings[0].entityId).toBe(7)
    })

    it('returns empty for empty results', () => {
        expect(resolveFindings([], knowledge)).toEqual([])
    })
})

describe('resolveFindings with groups', () => {
    const knowledge: Record<string, KnowledgeEntry> = {
        'det-a': { summary: 'label A', description: 'desc A' },
        'det-b': { summary: 'label B', description: 'desc B' },
        'det-c': { summary: 'label C', description: 'desc C', docs: [{ label: 'C docs', url: 'https://c.com' }] },
        ungrouped: { summary: 'Ungrouped', description: 'Ungrouped desc' },
    }

    const group: GroupKnowledgeEntry = {
        id: 'my-group',
        ids: ['det-a', 'det-b', 'det-c'],
        summary: 'Group summary',
        description: (labels) => `Issues: ${labels.join(', ')}`,
        docs: [{ label: 'Group docs', url: 'https://group.com' }],
    }

    it.each([
        {
            name: '0 triggered members produces no finding',
            results: [],
            expected: [],
        },
        {
            name: '1 triggered member produces one grouped finding with single label',
            results: [{ id: 'det-a', severity: 'warning' as const }],
            expected: [
                {
                    id: 'my-group',
                    summary: 'Group summary',
                    description: 'Issues: label A',
                    severity: 'warning',
                    docs: [{ label: 'Group docs', url: 'https://group.com' }],
                },
            ],
        },
        {
            name: 'multiple triggered members produces one finding with combined labels',
            results: [
                { id: 'det-a', severity: 'info' as const },
                { id: 'det-b', severity: 'warning' as const },
            ],
            expected: [
                {
                    id: 'my-group',
                    summary: 'Group summary',
                    description: 'Issues: label A, label B',
                    severity: 'warning',
                    docs: [{ label: 'Group docs', url: 'https://group.com' }],
                },
            ],
        },
        {
            name: 'severity takes the highest among grouped members',
            results: [
                { id: 'det-a', severity: 'info' as const },
                { id: 'det-c', severity: 'error' as const },
            ],
            expected: [expect.objectContaining({ id: 'my-group', severity: 'error' })],
        },
        {
            name: 'mixed grouped and ungrouped results both appear',
            results: [
                { id: 'det-a', severity: 'warning' as const },
                { id: 'ungrouped', severity: 'info' as const },
            ],
            expected: [
                expect.objectContaining({ id: 'my-group' }),
                expect.objectContaining({ id: 'ungrouped', summary: 'Ungrouped' }),
            ],
        },
    ])('$name', ({ results, expected }) => {
        expect(resolveFindings(results, knowledge, [group])).toEqual(expected)
    })

    it('static string summary and description work without function calls', () => {
        const staticGroup: GroupKnowledgeEntry = {
            id: 'static-group',
            ids: ['det-a'],
            summary: 'Static summary',
            description: 'Static description',
        }
        const results = [{ id: 'det-a', severity: 'info' as const }]
        const findings = resolveFindings(results, knowledge, [staticGroup])
        expect(findings).toEqual([
            {
                id: 'static-group',
                summary: 'Static summary',
                description: 'Static description',
                severity: 'info',
                docs: undefined,
            },
        ])
    })
})
