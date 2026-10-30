import type { EvaluationConditionSet, EvaluationConfig } from '../types'
import { reportText, triggerText } from './evaluationSummary'

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

describe('evaluation sentence parts', () => {
    test.each([
        { name: 'all traffic', input: evaluation({}), expected: '100% of all traces' },
        {
            name: 'sampled, filtered traffic',
            input: evaluation({ conditions: [filtered(10, 2)] }),
            expected: '10% of matching traces (2 filters)',
        },
        {
            name: 'sentiment counts generations, whatever target is stored',
            input: evaluation({ evaluation_type: 'sentiment' } as Partial<EvaluationConfig>),
            expected: '100% of all generations',
        },
        {
            name: 'several condition sets sample on their own, so no single percentage',
            input: evaluation({ conditions: [filtered(100, 1), filtered(20, 0)] }),
            expected: '2 condition sets',
        },
    ])('triggers: $name', ({ input, expected }) => {
        expect(triggerText(input).replace(/\u00a0/g, ' ')).toEqual(expected)
    })

    test.each([
        { name: 'off', input: { enabled: false, frequency: 'scheduled' }, expected: 'never' },
        { name: 'scheduled', input: { enabled: true, frequency: 'scheduled' }, expected: 'weekly' },
        {
            name: 'by result count',
            input: { enabled: true, frequency: 'every_n' },
            expected: 'every 100 results',
        },
    ])('reports: $name', ({ input, expected }) => {
        expect(reportText({ scheduleCadence: 'weekly', triggerThreshold: 100, ...input })).toEqual(expected)
    })
})
