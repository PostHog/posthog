import type { EvaluationConditionSet, EvaluationConfig } from '../types'
import { summarySentence } from './evaluationSummary'

const evaluation = (overrides: Partial<EvaluationConfig>): EvaluationConfig =>
    ({
        name: 'Helpfulness',
        evaluation_type: 'llm_judge',
        evaluation_config: { prompt: 'Is it helpful?' },
        output_type: 'boolean',
        output_config: {},
        target: 'trace',
        conditions: [{ id: 'c1', rollout_percentage: 100, properties: [] }],
        ...overrides,
    }) as unknown as EvaluationConfig

const filtered = (rollout: number, filters: number): EvaluationConditionSet => ({
    id: `c-${rollout}`,
    rollout_percentage: rollout,
    properties: Array.from({ length: filters }, (_, i) => ({ key: `p${i}`, type: 'event' })) as any,
})

describe('summarySentence', () => {
    test.each([
        {
            name: 'judge with its model and daily volume',
            input: { evaluation: evaluation({}), usesDecisionModel: false, modelName: 'gpt-4o-mini', runsPerDay: 14 },
            expected: 'Helpfulness runs an LLM judge (gpt-4o-mini) on 100% of all traces, about 14 a day.',
        },
        {
            name: 'decision model on sampled, filtered traffic',
            input: {
                evaluation: evaluation({ conditions: [filtered(10, 2)] }),
                usesDecisionModel: true,
                runsPerDay: null,
            },
            expected: 'Helpfulness runs a decision model on 10% of matching traces (2 filters).',
        },
        {
            name: 'sentiment always runs on generations, whatever target is stored',
            input: {
                evaluation: evaluation({ name: '', evaluation_type: 'sentiment' } as Partial<EvaluationConfig>),
                usesDecisionModel: false,
                runsPerDay: 3,
            },
            expected: 'This evaluation runs a sentiment classifier on 100% of all generations, about 3 a day.',
        },
        {
            name: 'several condition sets',
            input: {
                evaluation: evaluation({ evaluation_type: 'hog', conditions: [filtered(5, 1), filtered(50, 0)] }),
                usesDecisionModel: false,
                runsPerDay: null,
            },
            expected: 'Helpfulness runs your code on 2 condition sets.',
        },
    ])('$name', ({ input, expected }) => {
        // pluralize joins the count and noun with a non-breaking space.
        expect(summarySentence(input).replace(/\u00a0/g, ' ')).toEqual(expected)
    })
})
