import type { EvaluationConditionSet, EvaluationConfig } from '../types'
import { reportText, settleSummary, triggerText } from './evaluationSummary'

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
            name: 'by result count, at most daily',
            input: { enabled: true, frequency: 'every_n' },
            expected: 'every 100 results, at most once a day',
        },
        {
            name: 'by result count, at most hourly',
            input: { enabled: true, frequency: 'every_n', cooldownMinutes: 60 },
            expected: 'every 100 results, at most once an hour',
        },
        {
            name: 'by result count, a custom gap',
            input: { enabled: true, frequency: 'every_n', cooldownMinutes: 360 },
            expected: 'every 100 results, at most once every 6 hours',
        },
        {
            name: 'by result count, a gap saved in minutes through the API',
            input: { enabled: true, frequency: 'every_n', cooldownMinutes: 90 },
            expected: 'every 100 results, at most once every 90 minutes',
        },
    ])('reports: $name', ({ input, expected }) => {
        expect(
            reportText({ scheduleCadence: 'weekly', triggerThreshold: 100, cooldownMinutes: 1440, ...input })
        ).toEqual(expected)
    })

    test.each([
        { name: 'a generation runs at once', input: evaluation({ target: 'generation' }), expected: null },
        {
            name: 'a trace waits a fixed delay by default',
            input: evaluation({ target: 'trace', target_config: {} }),
            expected: 'It runs 30 minutes after the first matching generation.',
        },
        {
            name: 'a session waits for quiet by default',
            input: evaluation({ target: 'session', target_config: {} }),
            expected: 'It runs once the session has been quiet for 1 hour, or 1 day after it starts.',
        },
        {
            name: 'a stored quiet period wins over the default',
            input: evaluation({
                target: 'trace',
                target_config: { strategy: 'inactivity', quiet_period_seconds: 120, max_age_seconds: 3600 },
            } as Partial<EvaluationConfig>),
            expected: 'It runs once the trace has been quiet for 2 minutes, or 1 hour after it starts.',
        },
    ])('timing: $name', ({ input, expected }) => {
        expect(settleSummary(input)?.replace(/\u00a0/g, ' ') ?? null).toEqual(expected)
    })
})
