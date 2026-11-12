import { defaultCompositeExpression, updateScorerDraft } from './compositeFormulaDefaults'
import defaults from './compositeFormulaDefaults.fixtures.json'
import { createDraft, type ScoreDefinitionDraft } from './scoreDefinitionModalUtils'

const safe: ScoreDefinitionDraft['inputs'][number] = {
    alias: 'safe',
    name: 'Safety',
    definition_id: 'safety',
    scorer_version_id: 'safety-v1',
    kind: 'boolean',
    version: 1,
    latest_version: 1,
    latest_version_id: 'safety-v1',
    config: { true_is_failure: false },
}
const accurate: ScoreDefinitionDraft['inputs'][number] = {
    ...safe,
    alias: 'accuracy',
    kind: 'numeric',
    config: { passing_rule: { operator: 'gte', threshold: 0.8 } },
}
const base: ScoreDefinitionDraft = {
    ...createDraft('create'),
    calculation: 'composite',
    kind: 'boolean',
    inputs: [safe],
}

describe('composite formula defaults', () => {
    it.each(defaults)('$name stays compatible with the server parser fixtures', (example) => {
        expect(
            defaultCompositeExpression({
                ...base,
                kind: example.kind as ScoreDefinitionDraft['kind'],
                inputs: Array.from({ length: example.count }, (_, index) => ({
                    ...safe,
                    alias: `s${index}`,
                    kind: example.inputKind as ScoreDefinitionDraft['kind'],
                    config: example.inputConfig,
                })),
            })
        ).toBe(example.expression)
    })

    it('honors the minimum selections for categorical defaults', () => {
        const draft: ScoreDefinitionDraft = {
            ...base,
            kind: 'categorical',
            selectionMode: 'multiple',
            categoricalMinSelections: '2',
            categoricalPassingEnabled: true,
            categoricalPassingCategories: ['good', 'clear'],
            options: ['good', 'clear', 'bad'].map((key) => ({ key, label: key })),
        }
        expect(defaultCompositeExpression(draft)).toBe('["good","clear"] if (safe) else ["bad","good"]')
        expect(defaultCompositeExpression({ ...draft, categoricalPassingCategories: ['good'] })).toBeNull()
    })

    it.each([
        ['boolean', '(safe) and (accuracy >= 0.8)'],
        ['numeric', '(number(safe) + accuracy) / 2'],
        ['categorical', '"good" if (safe) and (accuracy >= 0.8) else "bad"'],
    ] as const)('builds a %s formula from mixed input types', (kind, expression) => {
        expect(defaultCompositeExpression({ ...base, kind, inputs: [safe, accurate] })).toBe(expression)
    })

    it('uses false-is-passing rules and excludes failing categories in multi-select inputs', () => {
        expect(
            defaultCompositeExpression({
                ...base,
                inputs: [
                    { ...safe, config: { true_is_failure: true } },
                    {
                        ...safe,
                        alias: 'relevance',
                        kind: 'categorical',
                        config: {
                            options: [
                                { key: 'good', label: 'Good' },
                                { key: 'bad', label: 'Bad' },
                            ],
                            passing_rule: { categories: ['good'] },
                            selection_mode: 'multiple',
                        },
                    },
                ],
            })
        ).toBe('(not safe) and (("good" in relevance) and not ("bad" in relevance))')
    })

    it('does not invent a passing threshold for an unconfigured numeric input', () => {
        expect(defaultCompositeExpression({ ...base, inputs: [{ ...accurate, config: {} }] })).toBeNull()
    })

    it('does not generate a formula longer than the editor and server accept', () => {
        expect(
            defaultCompositeExpression({
                ...base,
                inputs: Array.from({ length: 16 }, (_, index) => ({
                    ...safe,
                    alias: `s${index}`,
                    kind: 'categorical',
                    config: {
                        options: [{ key: 'a'.repeat(128), label: 'Passing' }],
                        passing_rule: { categories: ['a'.repeat(128)] },
                    },
                })),
            })
        ).toBeNull()
    })

    it('returns false for an all-pass result when the composite uses false as passing', () => {
        expect(defaultCompositeExpression({ ...base, booleanPassing: 'false' })).toBe('not ((safe))')
    })

    it('updates automatic formulas but preserves any manual edit, including clearing the formula', () => {
        const automatic = updateScorerDraft(base, 'inputs', [safe, accurate])
        expect(automatic.expression).toBe('(safe) and (accuracy >= 0.8)')
        for (const expression of ['safe', '']) {
            const manual = updateScorerDraft(automatic, 'expression', expression)
            expect(updateScorerDraft(manual, 'inputs', [safe]).expression).toBe(expression)
            expect(updateScorerDraft(manual, 'kind', 'numeric').expression).toBe(expression)
            expect(updateScorerDraft(manual, 'expressionIsCustom', false).expression).toBe(automatic.expression)
        }
    })
})
