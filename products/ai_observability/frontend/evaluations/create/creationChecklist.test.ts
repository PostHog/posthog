import { runRate, summarizeVolume } from '../evaluationVolume'
import type { EvaluationConfig } from '../types'
import { categoryKey } from './categoryKey'
import { type ChecklistInput, categoryResultError, creationChecklist } from './creationChecklist'

const judge = (prompt: string, name = 'Helpfulness'): EvaluationConfig =>
    ({
        name,
        evaluation_type: 'llm_judge',
        evaluation_config: { prompt },
        output_type: 'boolean',
        output_config: {},
        conditions: [{ id: 'c1', rollout_percentage: 100, properties: [] }],
    }) as unknown as EvaluationConfig

const input = (overrides: Partial<ChecklistInput>): ChecklistInput => ({
    evaluation: judge('Is it helpful?'),
    resultError: null,
    modelSelectionRequired: true,
    hasSelectedModel: true,
    hasAvailableModels: true,
    hasUnsetSampling: false,
    ...overrides,
})

const firstTodo = (overrides: Partial<ChecklistInput>): string | undefined =>
    creationChecklist(input(overrides)).find((item) => !item.done)?.todo

describe('creationChecklist', () => {
    test.each([
        ['a complete judge', {}, undefined],
        ['a missing name', { evaluation: judge('Is it helpful?', '  ') }, 'Give the evaluation a name'],
        ['an empty prompt', { evaluation: judge('   ') }, 'Write the prompt the judge follows'],
        ['an invalid result setting', { resultError: 'Add at least one label' }, 'Add at least one label'],
        ['no model while models exist', { hasSelectedModel: false }, 'Pick the model that judges each run'],
        [
            'no model and no provider key',
            { hasSelectedModel: false, hasAvailableModels: false },
            'Add an API key for an AI provider, then pick a model',
        ],
        ['unset sampling', { hasUnsetSampling: true }, 'Set a sampling percentage between 0.1% and 100%'],
    ] as [string, Partial<ChecklistInput>, string | undefined][])('blocks create on %s', (_, overrides, expected) => {
        expect(firstTodo(overrides)).toBe(expected)
    })

    it('asks for no prompt, result or model on a sentiment evaluation', () => {
        const sentiment = { ...judge(''), evaluation_type: 'sentiment', output_type: 'sentiment' } as EvaluationConfig
        expect(
            creationChecklist(input({ evaluation: sentiment, modelSelectionRequired: false })).map((item) => item.key)
        ).toEqual(['name', 'sampling'])
    })

    test.each([
        [
            'samples each condition set by its own percentage',
            [
                { generations: 1000, units: 1000, rolloutPercentage: 10 },
                { generations: 50, units: 50, rolloutPercentage: 100 },
            ],
            'generation',
            { matchingGenerations: 1050, matchingUnits: 1050, runs: 150 },
        ],
        [
            'counts traces, not generations, for a trace evaluation',
            [{ generations: 900, units: 120, rolloutPercentage: 50 }],
            'trace',
            { matchingGenerations: 900, matchingUnits: 120, runs: 60 },
        ],
    ] as const)('estimates runs: %s', (_, conditions, target, expected) => {
        expect(summarizeVolume([...conditions], target)).toEqual({ target, ...expected })
    })

    test.each([
        [98, 'about 14 times a day'],
        [7, 'about once a day'],
        [3, 'about 3 times a week'],
        [1, 'once a week'],
        [0, 'less than once a week'],
    ])('describes %d runs a week as "%s"', (runs, expected) => {
        expect(runRate(runs)).toEqual(expected)
    })

    test.each([
        ['Resolved', 'resolved'],
        ['Handed off to a human', 'handed-off-to-a-human'],
        ['  Partly resolved (needs follow-up)! ', 'partly-resolved-needs-follow-up'],
        ['snake_case label', 'snake-case-label'],
        ['已解决', 'category-ef9uq'],
    ])('turns the category label %j into the stored key %j', (label, key) => {
        expect(categoryKey(label)).toBe(key)
        expect(key).toMatch(/^[a-z0-9]+(?:[_-][a-z0-9]+)*$/)
    })

    test.each([
        ['no categories', [], 'Add at least one category'],
        [
            'a nameless category',
            [{ key: '', label: '' }],
            'Give every category a name with at least one letter or number',
        ],
        [
            'a name with only symbols',
            [{ key: '', label: '!!' }],
            'Give every category a name with at least one letter or number',
        ],
        [
            'two names with the same key',
            [
                { key: 'resolved', label: 'Resolved' },
                { key: 'resolved', label: 'Resolved!' },
            ],
            'Give each category a different name',
        ],
        ['valid categories', [{ key: 'resolved', label: 'Resolved' }], null],
    ])('explains %s without mentioning keys', (_, options, expected) => {
        expect(categoryResultError({ options })).toBe(expected)
    })
})
