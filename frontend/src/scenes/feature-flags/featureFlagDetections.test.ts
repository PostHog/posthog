import { FeatureFlagEvaluationRuntime, PropertyFilterType, PropertyOperator } from '~/types'

import { FeatureFlagDetectionContext, featureFlagDetections } from './featureFlagDetections'

function buildFlagFixture(
    overrides: Partial<FeatureFlagDetectionContext> & {
        properties?: FeatureFlagDetectionContext['filters']['groups'][number]['properties']
        evaluationRuntime?: FeatureFlagEvaluationRuntime
    } = {}
): FeatureFlagDetectionContext {
    const { properties, evaluationRuntime, ...rest } = overrides
    return {
        id: 1,
        key: 'test-flag',
        name: '',
        filters: {
            groups: [{ properties: properties ?? [], rollout_percentage: 100 }],
        },
        deleted: false,
        active: true,
        ensure_experience_continuity: null,
        created_by: null,
        created_at: null,
        updated_at: null,
        version: null,
        last_modified_by: null,
        experiment_set: null,
        features: null,
        surveys: null,
        can_edit: true,
        tags: [],
        evaluation_tags: [],
        is_remote_configuration: false,
        has_encrypted_payloads: false,
        status: 'ACTIVE',
        evaluation_runtime: evaluationRuntime ?? FeatureFlagEvaluationRuntime.ALL,
        _cohortsById: {},
        ...rest,
    } as FeatureFlagDetectionContext
}

function triggerEntry(id: string, context: FeatureFlagDetectionContext): boolean {
    const entry = featureFlagDetections.find((e) => e.id === id)
    if (!entry) {
        throw new Error(`Detection entry "${id}" not found`)
    }
    return entry.trigger(context)
}

describe('featureFlagDetections', () => {
    describe('registry shape', () => {
        it.each(featureFlagDetections.map((e) => [e.id, e]))('%s has required fields', (_id, entry) => {
            expect(entry.id).toBeTruthy()
            expect(['info', 'warning', 'error']).toContain(entry.severity)
            expect(typeof entry.trigger).toBe('function')
        })
    })

    describe('non-instant-properties', () => {
        it.each([
            [
                'triggers for person property not in instant list',
                { key: 'email', type: PropertyFilterType.Person },
                true,
            ],
            ['triggers for cohort property', { key: 'id', type: PropertyFilterType.Cohort, value: 1 }, true],
            [
                'does not trigger for geoip property',
                { key: '$geoip_country_code', type: PropertyFilterType.Person },
                false,
            ],
            ['does not trigger for distinct_id', { key: 'distinct_id', type: PropertyFilterType.Person }, false],
        ])('%s', (_label, property, expected) => {
            const context = buildFlagFixture({ properties: [property as any] })
            expect(triggerEntry('non-instant-properties', context)).toBe(expected)
        })

        it('does not trigger when all properties are instant', () => {
            const context = buildFlagFixture({
                properties: [
                    {
                        key: '$geoip_city_name',
                        type: PropertyFilterType.Person,
                        operator: PropertyOperator.Exact,
                        value: 'SF',
                    },
                    {
                        key: '$geoip_country_code',
                        type: PropertyFilterType.Person,
                        operator: PropertyOperator.Exact,
                        value: 'US',
                    },
                ],
            })
            expect(triggerEntry('non-instant-properties', context)).toBe(false)
        })

        it('does not trigger for empty properties', () => {
            const context = buildFlagFixture({ properties: [] })
            expect(triggerEntry('non-instant-properties', context)).toBe(false)
        })
    })

    describe('is-not-set-operator', () => {
        it('detects is_not_set operator on server runtime', () => {
            const context = buildFlagFixture({
                properties: [
                    { key: 'email', type: PropertyFilterType.Person, operator: PropertyOperator.IsNotSet, value: '' },
                ],
                evaluationRuntime: FeatureFlagEvaluationRuntime.SERVER,
            })
            expect(triggerEntry('is-not-set-operator', context)).toBe(true)
        })

        it('does not trigger for client runtime', () => {
            const context = buildFlagFixture({
                properties: [
                    { key: 'email', type: PropertyFilterType.Person, operator: PropertyOperator.IsNotSet, value: '' },
                ],
                evaluationRuntime: FeatureFlagEvaluationRuntime.CLIENT,
            })
            expect(triggerEntry('is-not-set-operator', context)).toBe(false)
        })

        it('does not trigger for exact operator', () => {
            const context = buildFlagFixture({
                properties: [
                    { key: 'email', type: PropertyFilterType.Person, operator: PropertyOperator.Exact, value: 'test' },
                ],
                evaluationRuntime: FeatureFlagEvaluationRuntime.SERVER,
            })
            expect(triggerEntry('is-not-set-operator', context)).toBe(false)
        })
    })

    describe('static-cohort', () => {
        it('triggers when static cohort is used', () => {
            const context = buildFlagFixture({
                properties: [{ key: 'id', type: PropertyFilterType.Cohort, value: 1, operator: PropertyOperator.In }],
                evaluationRuntime: FeatureFlagEvaluationRuntime.SERVER,
            })
            context._cohortsById = { 1: { id: 1, name: 'Static', is_static: true } as any }
            expect(triggerEntry('static-cohort', context)).toBe(true)
        })

        it('does not trigger when cohort is not loaded', () => {
            const context = buildFlagFixture({
                properties: [{ key: 'id', type: PropertyFilterType.Cohort, value: 1, operator: PropertyOperator.In }],
                evaluationRuntime: FeatureFlagEvaluationRuntime.SERVER,
            })
            expect(triggerEntry('static-cohort', context)).toBe(false)
        })

        it('does not trigger for non-static cohorts', () => {
            const context = buildFlagFixture({
                properties: [{ key: 'id', type: PropertyFilterType.Cohort, value: 1, operator: PropertyOperator.In }],
                evaluationRuntime: FeatureFlagEvaluationRuntime.SERVER,
            })
            context._cohortsById = { 1: { id: 1, name: 'Dynamic', is_static: false } as any }
            expect(triggerEntry('static-cohort', context)).toBe(false)
        })

        it('does not trigger for client runtime', () => {
            const context = buildFlagFixture({
                properties: [{ key: 'id', type: PropertyFilterType.Cohort, value: 1, operator: PropertyOperator.In }],
                evaluationRuntime: FeatureFlagEvaluationRuntime.CLIENT,
            })
            context._cohortsById = { 1: { id: 1, name: 'Static', is_static: true } as any }
            expect(triggerEntry('static-cohort', context)).toBe(false)
        })
    })

    describe('regex-lookahead', () => {
        it.each([
            ['positive lookahead (?=)', 'test(?=@posthog)', true],
            ['negative lookahead (?!)', 'posthog(?!\\.org)', true],
            ['escaped lookahead', '\\(?=test\\)', false],
            ['no lookahead', '^[a-z]+@posthog\\.com$', false],
        ])('detects %s', (_label, value, expected) => {
            const context = buildFlagFixture({
                properties: [
                    { key: 'email', type: PropertyFilterType.Person, operator: PropertyOperator.Regex, value },
                ],
                evaluationRuntime: FeatureFlagEvaluationRuntime.SERVER,
            })
            expect(triggerEntry('regex-lookahead', context)).toBe(expected)
        })

        it('does not trigger for non-regex operators', () => {
            const context = buildFlagFixture({
                properties: [
                    {
                        key: 'email',
                        type: PropertyFilterType.Person,
                        operator: PropertyOperator.Exact,
                        value: '(?=test)',
                    },
                ],
                evaluationRuntime: FeatureFlagEvaluationRuntime.SERVER,
            })
            expect(triggerEntry('regex-lookahead', context)).toBe(false)
        })
    })

    describe('regex-lookbehind', () => {
        it.each([
            ['positive lookbehind (?<=)', '(?<=@)posthog', true],
            ['negative lookbehind (?<!)', '(?<!admin@)posthog', true],
            ['no lookbehind', '^[a-z]+@posthog\\.com$', false],
        ])('detects %s', (_label, value, expected) => {
            const context = buildFlagFixture({
                properties: [
                    { key: 'email', type: PropertyFilterType.Person, operator: PropertyOperator.Regex, value },
                ],
                evaluationRuntime: FeatureFlagEvaluationRuntime.SERVER,
            })
            expect(triggerEntry('regex-lookbehind', context)).toBe(expected)
        })
    })

    describe('regex-backreferences', () => {
        it.each([
            ['\\1', '(\\w+)\\1', true],
            ['\\2', '(a)(b)\\2', true],
            ['\\9', 'test\\9', true],
            ['\\0 is not a backreference', 'test\\0', false],
            ['groups without backrefs', '(test|prod)@(posthog|example)\\.(com|org)', false],
            ['numeric value without regex operator', '123', false],
        ])('handles %s', (_label, value, expected) => {
            const context = buildFlagFixture({
                properties: [
                    {
                        key: 'text',
                        type: PropertyFilterType.Person,
                        operator:
                            expected !== false || value === '123' ? PropertyOperator.Regex : PropertyOperator.Regex,
                        value,
                    },
                ],
                evaluationRuntime: FeatureFlagEvaluationRuntime.SERVER,
            })
            expect(triggerEntry('regex-backreferences', context)).toBe(expected)
        })
    })

    describe('cross-cutting', () => {
        it('ALL runtime shows warnings since local eval applies to server-side', () => {
            const context = buildFlagFixture({
                properties: [
                    {
                        key: 'email',
                        type: PropertyFilterType.Person,
                        operator: PropertyOperator.Regex,
                        value: 'test(?=@)',
                    },
                ],
                evaluationRuntime: FeatureFlagEvaluationRuntime.ALL,
            })
            expect(triggerEntry('regex-lookahead', context)).toBe(true)
        })

        it('detects multiple issues across properties', () => {
            const context = buildFlagFixture({
                properties: [
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
                ],
                evaluationRuntime: FeatureFlagEvaluationRuntime.SERVER,
            })
            expect(triggerEntry('regex-lookahead', context)).toBe(true)
            expect(triggerEntry('regex-lookbehind', context)).toBe(true)
            expect(triggerEntry('regex-backreferences', context)).toBe(true)
        })

        it('detects all issues in a single pattern', () => {
            const context = buildFlagFixture({
                properties: [
                    {
                        key: 'text',
                        type: PropertyFilterType.Person,
                        operator: PropertyOperator.Regex,
                        value: '(?=test)(?<=@)(\\w+)\\1',
                    },
                ],
                evaluationRuntime: FeatureFlagEvaluationRuntime.SERVER,
            })
            expect(triggerEntry('regex-lookahead', context)).toBe(true)
            expect(triggerEntry('regex-lookbehind', context)).toBe(true)
            expect(triggerEntry('regex-backreferences', context)).toBe(true)
        })

        it('only checks regex operators, not exact or contains', () => {
            const context = buildFlagFixture({
                properties: [
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
                ],
                evaluationRuntime: FeatureFlagEvaluationRuntime.SERVER,
            })
            expect(triggerEntry('regex-lookahead', context)).toBe(false)
            expect(triggerEntry('regex-lookbehind', context)).toBe(false)
        })

        it('converts value to string before checking', () => {
            const context = buildFlagFixture({
                properties: [
                    {
                        key: 'number',
                        type: PropertyFilterType.Person,
                        operator: PropertyOperator.Regex,
                        value: 123 as any,
                    },
                ],
                evaluationRuntime: FeatureFlagEvaluationRuntime.SERVER,
            })
            expect(triggerEntry('regex-lookahead', context)).toBe(false)
            expect(triggerEntry('regex-lookbehind', context)).toBe(false)
            expect(triggerEntry('regex-backreferences', context)).toBe(false)
        })
    })
})
