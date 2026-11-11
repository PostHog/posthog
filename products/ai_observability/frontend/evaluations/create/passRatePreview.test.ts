import type { EvaluationOutputConfig, EvaluationOutputType } from '../types'
import { passRatePreview } from './passRatePreview'

describe('passRatePreview', () => {
    it.each<[string, EvaluationOutputType, EvaluationOutputConfig, (boolean | null)[]]>([
        ['true passes', 'boolean', {}, [true, true, false, true]],
        ['false passes', 'boolean', { true_is_failure: true }, [false, false, true, false]],
        [
            'scores at least 3 pass',
            'numeric',
            { min: 1, max: 5, passing_rule: { operator: 'gte', threshold: 3 } },
            [true, true, true, false],
        ],
        ['a score with no passing score is ungraded', 'numeric', { min: 1, max: 5 }, [null, null, null, null]],
        [
            'only marked categories pass',
            'categorical',
            {
                options: [
                    { key: 'resolved', label: 'Resolved' },
                    { key: 'unresolved', label: 'Unresolved' },
                ],
                passing_rule: { categories: ['resolved'] },
            },
            [true, false, true, true],
        ],
    ])('%s', (_name, outputType, config, expected) => {
        expect(passRatePreview(outputType, config).map((run) => run.passes)).toEqual(expected)
    })

    it.each<[string, EvaluationOutputConfig, string[]]>([
        [
            'a fractional range keeps its decimals',
            { min: 0.1, max: 0.5 },
            ['0.5 / 0.5', '0.4 / 0.5', '0.3 / 0.5', '0.2 / 0.5'],
        ],
        [
            'a range of thousandths',
            { min: 0.001, max: 0.005 },
            ['0.005 / 0.005', '0.004 / 0.005', '0.003 / 0.005', '0.002 / 0.005'],
        ],
        ['a range with only a lowest score', { min: 10 }, ['14 / 14', '13 / 14', '12 / 14', '11 / 14']],
    ])('example scores stay inside %s', (_name, config, expected) => {
        const runs = passRatePreview('numeric', config)
        expect(runs.map((run) => run.value)).toEqual(expected)
        expect(runs.every((run) => run.fill !== undefined && run.fill >= 0 && run.fill <= 1)).toBe(true)
    })
})
