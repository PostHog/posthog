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
                warning:
                    'This flag cannot be evaluated in client environments. Release conditions contain unsupported regex patterns (lookahead).',
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
                warning:
                    'This flag cannot be evaluated in client environments. Release conditions contain unsupported regex patterns (lookahead).',
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
                warning:
                    'This flag cannot be evaluated in client environments. Release conditions contain unsupported regex patterns (lookbehind).',
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
                warning:
                    'This flag cannot be evaluated in client environments. Release conditions contain unsupported regex patterns (lookbehind).',
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
                    warning:
                        'This flag cannot be evaluated in client environments. Release conditions contain unsupported regex patterns (backreferences).',
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
            expect(warning).toContain('This flag cannot be evaluated in client environments')
            expect(warning).toContain('lookahead')
            expect(warning).toContain('lookbehind')
            expect(warning).toContain('backreferences')
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
            expect(warning).toContain('lookahead')
            expect(warning).toContain('lookbehind')
            expect(warning).toContain('backreferences')
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
                warning:
                    'This flag cannot be evaluated in client environments. Release conditions contain unsupported regex patterns (lookahead).',
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
                warning:
                    'This flag cannot be evaluated in client environments. Release conditions contain unsupported regex patterns (lookahead).',
            })
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
