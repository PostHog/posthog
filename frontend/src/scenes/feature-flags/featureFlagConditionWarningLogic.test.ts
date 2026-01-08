import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'
import { AnyPropertyFilter, FeatureFlagEvaluationRuntime, PropertyFilterType, PropertyOperator } from '~/types'

import { featureFlagConditionWarningLogic } from './featureFlagConditionWarningLogic'

describe('featureFlagConditionWarningLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    describe('server runtime', () => {
        it('returns no warning for server evaluation', () => {
            const properties: AnyPropertyFilter[] = [
                {
                    key: 'email',
                    type: PropertyFilterType.Person,
                    operator: PropertyOperator.Regex,
                    value: '(?=test)',
                },
            ]

            const logic = featureFlagConditionWarningLogic({
                properties,
                evaluationRuntime: FeatureFlagEvaluationRuntime.SERVER,
            })
            logic.mount()

            expectLogic(logic).toMatchValues({
                warning: undefined,
            })
        })
    })

    describe('client runtime - no unsupported features', () => {
        it('returns no warning when no regex properties exist', () => {
            const properties: AnyPropertyFilter[] = [
                {
                    key: 'email',
                    type: PropertyFilterType.Person,
                    operator: PropertyOperator.Exact,
                    value: 'test@posthog.com',
                },
            ]

            const logic = featureFlagConditionWarningLogic({
                properties,
                evaluationRuntime: FeatureFlagEvaluationRuntime.CLIENT,
            })
            logic.mount()

            expectLogic(logic).toMatchValues({
                warning: undefined,
            })
        })

        it('returns no warning for regex without unsupported features', () => {
            const properties: AnyPropertyFilter[] = [
                {
                    key: 'email',
                    type: PropertyFilterType.Person,
                    operator: PropertyOperator.Regex,
                    value: '^[a-z]+@posthog\\.com$',
                },
                {
                    key: 'email',
                    type: PropertyFilterType.Person,
                    operator: PropertyOperator.Regex,
                    value: '\\(?=test\\)', // lookahead pattern escaped
                },
            ]

            const logic = featureFlagConditionWarningLogic({
                properties,
                evaluationRuntime: FeatureFlagEvaluationRuntime.CLIENT,
            })
            logic.mount()

            expectLogic(logic).toMatchValues({
                warning: undefined,
            })
        })

        it('returns no warning for empty properties', () => {
            const logic = featureFlagConditionWarningLogic({
                properties: [],
                evaluationRuntime: FeatureFlagEvaluationRuntime.CLIENT,
            })
            logic.mount()

            expectLogic(logic).toMatchValues({
                warning: undefined,
            })
        })
    })

    describe('client runtime - lookahead detection', () => {
        it('detects positive lookahead (?=)', () => {
            const properties: AnyPropertyFilter[] = [
                {
                    key: 'email',
                    type: PropertyFilterType.Person,
                    operator: PropertyOperator.Regex,
                    value: 'test(?=@posthog)',
                },
            ]

            const logic = featureFlagConditionWarningLogic({
                properties,
                evaluationRuntime: FeatureFlagEvaluationRuntime.CLIENT,
            })
            logic.mount()

            expectLogic(logic).toMatchValues({
                warning: 'This flag cannot be evaluated locally. Unsupported features: lookahead in regex.',
            })
        })

        it('detects negative lookahead (?!)', () => {
            const properties: AnyPropertyFilter[] = [
                {
                    key: 'email',
                    type: PropertyFilterType.Person,
                    operator: PropertyOperator.Regex,
                    value: 'posthog(?!\\.org)',
                },
            ]

            const logic = featureFlagConditionWarningLogic({
                properties,
                evaluationRuntime: FeatureFlagEvaluationRuntime.CLIENT,
            })
            logic.mount()

            expectLogic(logic).toMatchValues({
                warning: 'This flag cannot be evaluated locally. Unsupported features: lookahead in regex.',
            })
        })
    })

    describe('client runtime - lookbehind detection', () => {
        it('detects positive lookbehind (?<=)', () => {
            const properties: AnyPropertyFilter[] = [
                {
                    key: 'email',
                    type: PropertyFilterType.Person,
                    operator: PropertyOperator.Regex,
                    value: '(?<=@)posthog',
                },
            ]

            const logic = featureFlagConditionWarningLogic({
                properties,
                evaluationRuntime: FeatureFlagEvaluationRuntime.CLIENT,
            })
            logic.mount()

            expectLogic(logic).toMatchValues({
                warning: 'This flag cannot be evaluated locally. Unsupported features: lookbehind in regex.',
            })
        })

        it('detects negative lookbehind (?<!)', () => {
            const properties: AnyPropertyFilter[] = [
                {
                    key: 'email',
                    type: PropertyFilterType.Person,
                    operator: PropertyOperator.Regex,
                    value: '(?<!admin@)posthog',
                },
            ]

            const logic = featureFlagConditionWarningLogic({
                properties,
                evaluationRuntime: FeatureFlagEvaluationRuntime.CLIENT,
            })
            logic.mount()

            expectLogic(logic).toMatchValues({
                warning: 'This flag cannot be evaluated locally. Unsupported features: lookbehind in regex.',
            })
        })
    })

    describe('client runtime - backreference detection', () => {
        it('detects backreferences \\1 through \\9', () => {
            const testCases = ['(\\w+)\\1', '(a)(b)\\2', 'repeat(\\w+)word\\1again', '(x)(y)(z)\\3', 'test\\9']

            testCases.forEach((value) => {
                const properties: AnyPropertyFilter[] = [
                    {
                        key: 'text',
                        type: PropertyFilterType.Person,
                        operator: PropertyOperator.Regex,
                        value,
                    },
                ]

                const logic = featureFlagConditionWarningLogic({
                    properties,
                    evaluationRuntime: FeatureFlagEvaluationRuntime.CLIENT,
                })
                logic.mount()

                expectLogic(logic).toMatchValues({
                    warning: 'This flag cannot be evaluated locally. Unsupported features: backreferences in regex.',
                })

                logic.unmount()
            })
        })

        it('does not detect \\0 as backreference', () => {
            const properties: AnyPropertyFilter[] = [
                {
                    key: 'text',
                    type: PropertyFilterType.Person,
                    operator: PropertyOperator.Regex,
                    value: 'test\\0',
                },
            ]

            const logic = featureFlagConditionWarningLogic({
                properties,
                evaluationRuntime: FeatureFlagEvaluationRuntime.CLIENT,
            })
            logic.mount()

            expectLogic(logic).toMatchValues({
                warning: undefined,
            })
        })
    })

    describe('client runtime - multiple unsupported features', () => {
        it('reports all unsupported features when multiple exist', () => {
            const properties: AnyPropertyFilter[] = [
                {
                    key: 'text',
                    type: PropertyFilterType.Person,
                    operator: PropertyOperator.Regex,
                    value: '(?=test)(?<=@)(\\w+)\\1',
                },
            ]

            const logic = featureFlagConditionWarningLogic({
                properties,
                evaluationRuntime: FeatureFlagEvaluationRuntime.CLIENT,
            })
            logic.mount()

            const warning = logic.values.warning as string
            expect(warning).toContain('This flag cannot be evaluated locally')
            expect(warning).toContain('lookahead in regex')
            expect(warning).toContain('lookbehind in regex')
            expect(warning).toContain('backreferences in regex')
        })

        it('reports features from multiple properties', () => {
            const properties: AnyPropertyFilter[] = [
                {
                    key: 'email',
                    type: PropertyFilterType.Person,
                    operator: PropertyOperator.Regex,
                    value: 'test(?=@)',
                },
                {
                    key: 'name',
                    type: PropertyFilterType.Person,
                    operator: PropertyOperator.Regex,
                    value: '(?<=prefix)name',
                },
                {
                    key: 'text',
                    type: PropertyFilterType.Person,
                    operator: PropertyOperator.Regex,
                    value: '(\\w+)\\1',
                },
            ]

            const logic = featureFlagConditionWarningLogic({
                properties,
                evaluationRuntime: FeatureFlagEvaluationRuntime.CLIENT,
            })
            logic.mount()

            const warning = logic.values.warning as string
            expect(warning).toContain('lookahead in regex')
            expect(warning).toContain('lookbehind in regex')
            expect(warning).toContain('backreferences in regex')
        })
    })

    describe('client runtime - mixed property operators', () => {
        it('only checks regex operators', () => {
            const properties: AnyPropertyFilter[] = [
                {
                    key: 'email',
                    type: PropertyFilterType.Person,
                    operator: PropertyOperator.Exact,
                    value: '(?=test)',
                },
                {
                    key: 'name',
                    type: PropertyFilterType.Person,
                    operator: PropertyOperator.IContains,
                    value: '(?<=prefix)',
                },
            ]

            const logic = featureFlagConditionWarningLogic({
                properties,
                evaluationRuntime: FeatureFlagEvaluationRuntime.CLIENT,
            })
            logic.mount()

            expectLogic(logic).toMatchValues({
                warning: undefined,
            })
        })

        it('detects unsupported features only in regex properties', () => {
            const properties: AnyPropertyFilter[] = [
                {
                    key: 'email',
                    type: PropertyFilterType.Person,
                    operator: PropertyOperator.Exact,
                    value: '(?=safe)',
                },
                {
                    key: 'text',
                    type: PropertyFilterType.Person,
                    operator: PropertyOperator.Regex,
                    value: 'test(?=@)',
                },
            ]

            const logic = featureFlagConditionWarningLogic({
                properties,
                evaluationRuntime: FeatureFlagEvaluationRuntime.CLIENT,
            })
            logic.mount()

            expectLogic(logic).toMatchValues({
                warning: 'This flag cannot be evaluated locally. Unsupported features: lookahead in regex.',
            })
        })
    })

    describe('ALL runtime', () => {
        it('behaves like client runtime', () => {
            const properties: AnyPropertyFilter[] = [
                {
                    key: 'email',
                    type: PropertyFilterType.Person,
                    operator: PropertyOperator.Regex,
                    value: 'test(?=@)',
                },
            ]

            const logic = featureFlagConditionWarningLogic({
                properties,
                evaluationRuntime: FeatureFlagEvaluationRuntime.ALL,
            })
            logic.mount()

            expectLogic(logic).toMatchValues({
                warning: 'This flag cannot be evaluated locally. Unsupported features: lookahead in regex.',
            })
        })
    })

    describe('client runtime - is_not_set operator', () => {
        it('detects is_not_set operator', () => {
            const properties: AnyPropertyFilter[] = [
                {
                    key: 'email',
                    type: PropertyFilterType.Person,
                    operator: PropertyOperator.IsNotSet,
                    value: '',
                },
            ]

            const logic = featureFlagConditionWarningLogic({
                properties,
                evaluationRuntime: FeatureFlagEvaluationRuntime.CLIENT,
            })
            logic.mount()

            expectLogic(logic).toMatchValues({
                warning: 'This flag cannot be evaluated locally. Unsupported features: is_not_set operator.',
            })
        })
    })

    describe('client runtime - static cohorts', () => {
        it('warns when static cohort is used', () => {
            const properties: AnyPropertyFilter[] = [
                {
                    key: 'id',
                    type: PropertyFilterType.Cohort,
                    value: 1,
                    operator: PropertyOperator.In,
                },
            ]

            const logic = featureFlagConditionWarningLogic({
                properties,
                evaluationRuntime: FeatureFlagEvaluationRuntime.CLIENT,
            })

            // Override cohortsById to include a static cohort before mounting so the logic
            // picks it up during initialization.
            const mockCohortsById = {
                1: { id: 1, name: 'Test Static Cohort', is_static: true },
            }
            logic.cache.cohortsById = mockCohortsById

            logic.mount()

            expect(logic.values.warning).toBe(
                'This flag cannot be evaluated locally. Unsupported features: static cohorts.'
            )
        })

        it('does not warn when cohort is not loaded yet', () => {
            const properties: AnyPropertyFilter[] = [
                {
                    key: 'id',
                    type: PropertyFilterType.Cohort,
                    value: 1,
                    operator: PropertyOperator.In,
                },
            ]

            const logic = featureFlagConditionWarningLogic({
                properties,
                evaluationRuntime: FeatureFlagEvaluationRuntime.CLIENT,
            })
            logic.mount()

            expectLogic(logic).toMatchValues({
                warning: undefined,
            })
        })

        it('does not warn for non-static cohorts', () => {
            const properties: AnyPropertyFilter[] = [
                {
                    key: 'id',
                    type: PropertyFilterType.Cohort,
                    value: 1,
                    operator: PropertyOperator.In,
                },
            ]

            const logic = featureFlagConditionWarningLogic({
                properties,
                evaluationRuntime: FeatureFlagEvaluationRuntime.CLIENT,
            })

            // Override cohortsById to include a non-static cohort before mounting
            const mockCohortsById = {
                1: { id: 1, name: 'Test Dynamic Cohort', is_static: false },
            }
            logic.cache.cohortsById = mockCohortsById

            logic.mount()

            expect(logic.values.warning).toBeUndefined()
        })
    })

    describe('edge cases', () => {
        it('handles regex patterns that look like but are not unsupported features', () => {
            const properties: AnyPropertyFilter[] = [
                {
                    key: 'text',
                    type: PropertyFilterType.Person,
                    operator: PropertyOperator.Regex,
                    value: 'plain text with \\d digits',
                },
            ]

            const logic = featureFlagConditionWarningLogic({
                properties,
                evaluationRuntime: FeatureFlagEvaluationRuntime.CLIENT,
            })
            logic.mount()

            expectLogic(logic).toMatchValues({
                warning: undefined,
            })
        })

        it('handles complex regex with groups but no backreferences', () => {
            const properties: AnyPropertyFilter[] = [
                {
                    key: 'email',
                    type: PropertyFilterType.Person,
                    operator: PropertyOperator.Regex,
                    value: '(test|prod)@(posthog|example)\\.(com|org)',
                },
            ]

            const logic = featureFlagConditionWarningLogic({
                properties,
                evaluationRuntime: FeatureFlagEvaluationRuntime.CLIENT,
            })
            logic.mount()

            expectLogic(logic).toMatchValues({
                warning: undefined,
            })
        })

        it('converts value to string before checking', () => {
            const properties: AnyPropertyFilter[] = [
                {
                    key: 'number',
                    type: PropertyFilterType.Person,
                    operator: PropertyOperator.Regex,
                    value: 123,
                },
            ]

            const logic = featureFlagConditionWarningLogic({
                properties,
                evaluationRuntime: FeatureFlagEvaluationRuntime.CLIENT,
            })
            logic.mount()

            expectLogic(logic).toMatchValues({
                warning: undefined,
            })
        })
    })
})
