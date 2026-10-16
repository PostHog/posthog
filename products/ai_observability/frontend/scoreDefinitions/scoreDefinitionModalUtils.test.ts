import type { ScoreDefinitionApi, ScoreDefinitionConfigApi } from '../generated/api.schemas'
import { buildConfigFromDraft, createDraft, validateDraft } from './scoreDefinitionModalUtils'

const definition: ScoreDefinitionApi = {
    id: 'scorer-example',
    name: 'Answer quality',
    description: '',
    kind: 'boolean',
    config: {},
    archived: false,
    current_version: 1,
    current_version_id: 'version-example',
    team: 1,
    created_by: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
}

describe('scorer form configuration', () => {
    it.each([
        ['single', [], 'Choose at least one passing category.'],
        ['single', ['missing'], 'Choose passing categories from the configured options.'],
        ['single', ['good'], undefined],
        ['multiple', [], undefined],
    ] as const)('validates categorical passing rules for %s with %j', (selectionMode, categories, error) => {
        const draft = {
            ...createDraft('create'),
            name: 'Quality',
            selectionMode,
            categoricalPassingEnabled: true,
            categoricalPassingCategories: [...categories],
        }
        expect(validateDraft('create', draft)).toBe(error)
        expect(buildConfigFromDraft({ ...draft, categoricalPassingEnabled: false })).not.toHaveProperty('passing_rule')
    })

    it.each<{ kind: ScoreDefinitionApi['kind']; config: ScoreDefinitionConfigApi }>([
        {
            kind: 'categorical',
            config: { options: [{ key: 'good', label: 'Good' }], passing_rule: { categories: ['good'] } },
        },
        { kind: 'boolean', config: { true_is_failure: false } },
        { kind: 'boolean', config: { true_is_failure: true } },
        { kind: 'boolean', config: { true_label: 'Flagged', false_label: 'Clear', true_is_failure: true } },
        { kind: 'numeric', config: { passing_rule: { operator: 'gte', threshold: 0 } } },
        { kind: 'numeric', config: { passing_rule: { operator: 'lte', threshold: -1 } } },
    ])('preserves $kind configuration on edit and duplication: $config', ({ kind, config }) => {
        for (const mode of ['config', 'duplicate'] as const) {
            expect(buildConfigFromDraft(createDraft(mode, { ...definition, kind, config }))).toEqual(config)
        }
    })

    it.each([{}, { true_is_failure: null }])('defaults legacy boolean polarity to true passing: %j', (config) => {
        for (const mode of ['config', 'duplicate'] as const) {
            const existing = createDraft(mode, { ...definition, config })
            expect(existing.booleanPassing).toBe('true')
            expect(buildConfigFromDraft(existing)).toEqual({ true_is_failure: false })
        }

        const created = { ...createDraft('create'), kind: 'boolean' as const }
        expect(buildConfigFromDraft(created)).toEqual({
            true_label: 'True',
            false_label: 'False',
            true_is_failure: false,
        })
    })

    it.each([
        { numericPassingThreshold: '', error: 'Enter a valid number for the passing threshold.' },
        { numericPassingThreshold: 'Infinity', error: 'Enter a valid number for the passing threshold.' },
        { numericPassingThreshold: '-1', error: 'Set the passing threshold within the score bounds.' },
        { numericPassingThreshold: '11', error: 'Set the passing threshold within the score bounds.' },
        { numericPassingThreshold: '0', error: undefined },
        { numericPassingThreshold: '10', error: undefined },
    ])('validates enabled passing threshold $numericPassingThreshold', ({ numericPassingThreshold, error }) => {
        const draft = {
            ...createDraft('config', definition),
            kind: 'numeric' as const,
            numericMin: '0',
            numericMax: '10',
            numericPassingEnabled: true,
            numericPassingThreshold,
        }
        expect(validateDraft('config', draft)).toBe(error)
        expect(validateDraft('config', { ...draft, numericPassingEnabled: false })).toBeUndefined()
        expect(buildConfigFromDraft({ ...draft, numericPassingEnabled: false })).toEqual({ min: 0, max: 10 })
    })

    it.each([
        {
            categoricalMinSelections: '0',
            categoricalMaxSelections: '',
            error: 'Minimum selections must be at least 1.',
        },
        {
            categoricalMinSelections: '',
            categoricalMaxSelections: '0',
            error: 'Maximum selections must be at least 1.',
        },
        { categoricalMinSelections: '1', categoricalMaxSelections: '1', error: undefined },
        { categoricalMinSelections: '', categoricalMaxSelections: '', error: undefined },
    ])(
        'validates multiple selection bounds min=$categoricalMinSelections max=$categoricalMaxSelections',
        ({ categoricalMinSelections, categoricalMaxSelections, error }) => {
            const draft = {
                ...createDraft('config', {
                    ...definition,
                    kind: 'categorical',
                    config: {
                        options: [
                            { key: 'good', label: 'Good' },
                            { key: 'bad', label: 'Bad' },
                        ],
                    },
                }),
                selectionMode: 'multiple' as const,
                categoricalMinSelections,
                categoricalMaxSelections,
            }
            expect(validateDraft('config', draft)).toBe(error)
        }
    )
})
