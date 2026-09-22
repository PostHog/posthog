import { getProductEventPropertyValues } from './HogFunctionFiltersInternal'

describe('getProductEventPropertyValues', () => {
    it('suggests all activity scopes for the activity-log scope property', () => {
        const values = getProductEventPropertyValues('activity-log', 'scope')

        // ExperimentHoldout only exists in the generated backend-sourced enum, so it
        // catches a regression to the handwritten frontend ActivityScope enum
        expect(values).toEqual(
            expect.arrayContaining([{ name: 'FeatureFlag' }, { name: 'Insight' }, { name: 'ExperimentHoldout' }])
        )
    })

    it.each([
        // Keys without a statically known value set must suppress suggestions entirely,
        // because the events-table fallback would surface values from unrelated analytics events
        { contextId: 'activity-log' as const, propertyKey: 'detail.name', expected: [] },
        // Non-internal contexts keep the default events-table suggestions
        { contextId: 'error-tracking' as const, propertyKey: '$exception_types', expected: null },
        { contextId: 'standard' as const, propertyKey: 'scope', expected: null },
    ])('returns $expected for $propertyKey in the $contextId context', ({ contextId, propertyKey, expected }) => {
        expect(getProductEventPropertyValues(contextId, propertyKey)).toEqual(expected)
    })
})
