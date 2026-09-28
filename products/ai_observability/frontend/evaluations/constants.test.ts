import {
    EVALUATION_CATEGORIES_HOGQL,
    categoricalEvaluationPassedHogQL,
    categoricalEvaluationsPassedHogQL,
    categoricalOutputConfigError,
    categoricalResultPasses,
} from './constants'
import type { EvaluationConfig, EvaluationOutputConfig } from './types'

describe('categorical evaluation rules', () => {
    test.each<{
        selection_mode: EvaluationOutputConfig['selection_mode']
        passing_rule: EvaluationOutputConfig['passing_rule']
        error: string | null
    }>([
        { selection_mode: undefined, passing_rule: { categories: [] }, error: 'Choose at least one passing category.' },
        { selection_mode: 'single', passing_rule: { categories: [] }, error: 'Choose at least one passing category.' },
        { selection_mode: 'single', passing_rule: { categories: ['fast'] }, error: null },
        { selection_mode: 'single', passing_rule: null, error: null },
        { selection_mode: 'multiple', passing_rule: { categories: [] }, error: null },
    ])('validates $selection_mode with $passing_rule', ({ selection_mode, passing_rule, error }) => {
        expect(
            categoricalOutputConfigError({
                options: [{ key: 'fast', label: 'Fast' }],
                selection_mode,
                passing_rule,
            })
        ).toBe(error)
    })

    test.each<{
        rule: EvaluationOutputConfig['passing_rule']
        categories: string[] | null
        passed: boolean | null
    }>([
        { rule: null, categories: ['fast'], passed: null },
        { rule: { categories: [] }, categories: [], passed: true },
        { rule: { categories: [] }, categories: ['fast'], passed: false },
        { rule: { categories: ['fast'] }, categories: [], passed: false },
        { rule: { categories: ['fast'] }, categories: ['fast'], passed: true },
        { rule: { categories: ['fast'] }, categories: ['fast', 'slow'], passed: false },
        { rule: { categories: ['fast'] }, categories: null, passed: null },
    ])('grades $categories using $rule as $passed', ({ rule, categories, passed }) => {
        expect(categoricalResultPasses(categories, rule)).toBe(passed)
    })

    test.each<{
        rule: EvaluationOutputConfig['passing_rule']
        predicate: string
    }>([
        { rule: null, predicate: 'false' },
        { rule: { categories: [] }, predicate: `empty(${EVALUATION_CATEGORIES_HOGQL})` },
        {
            rule: { categories: ['fast'] },
            predicate: `notEmpty(${EVALUATION_CATEGORIES_HOGQL}) AND hasAll(['fast'], ${EVALUATION_CATEGORIES_HOGQL})`,
        },
    ])('builds the single-evaluation predicate for $rule', ({ rule, predicate }) => {
        expect(categoricalEvaluationPassedHogQL({ output_config: { passing_rule: rule } })).toBe(predicate)
    })

    test.each([false, true])('scopes mixed rules to their evaluation (empty rule first: %s)', (emptyFirst) => {
        const evaluations: Pick<EvaluationConfig, 'id' | 'output_type' | 'output_config'>[] = [
            { id: 'empty', output_type: 'categorical', output_config: { passing_rule: { categories: [] } } },
            { id: 'fast', output_type: 'categorical', output_config: { passing_rule: { categories: ['fast'] } } },
        ]
        if (!emptyFirst) {
            evaluations.reverse()
        }
        evaluations.push(
            { id: 'ungraded', output_type: 'categorical', output_config: {} },
            {
                id: 'numeric',
                output_type: 'numeric',
                output_config: { passing_rule: { operator: 'lte', threshold: 50 } },
            }
        )
        const ids = emptyFirst ? "'empty', 'fast'" : "'fast', 'empty'"
        const rules = emptyFirst ? "[], ['fast']" : "['fast'], []"
        const lookup = `arrayElement([${rules}], transform(properties.$ai_evaluation_id, [${ids}], [1, 2], 0))`
        expect(categoricalEvaluationsPassedHogQL(evaluations)).toBe(
            `properties.$ai_evaluation_id IN (${ids}) AND if(empty(${EVALUATION_CATEGORIES_HOGQL}), empty(${lookup}), hasAll(${lookup}, ${EVALUATION_CATEGORIES_HOGQL}))`
        )
    })

    it('never counts ungraded evaluations as passing', () => {
        expect(
            categoricalEvaluationsPassedHogQL([{ id: 'ungraded', output_type: 'categorical', output_config: {} }])
        ).toBe('false')
    })
})
