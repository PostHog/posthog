import { CyclotronJobFiltersType, PropertyFilterType, PropertyOperator } from '~/types'

import { getProductEventPropertyValues, setSimpleFilterValue } from './HogFunctionFiltersInternal'

describe('HogFunctionFiltersInternal', () => {
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

    describe('setSimpleFilterValue', () => {
        const options = [
            { label: 'Team activity', value: '$activity_log_entry_created' },
            { label: 'Early access feature updated', value: '$early_access_feature_updated' },
        ]
        // As created from one flag's Notifications tab
        const boundToFlag: CyclotronJobFiltersType = {
            source: 'internal-events',
            events: [
                {
                    id: '$activity_log_entry_created',
                    type: 'events',
                    properties: [
                        {
                            key: 'scope',
                            type: PropertyFilterType.Event,
                            value: ['FeatureFlag'],
                            operator: PropertyOperator.Exact,
                        },
                    ],
                },
            ],
            properties: [
                { key: 'item_id', type: PropertyFilterType.Event, value: ['42'], operator: PropertyOperator.Exact },
            ],
        }

        // Touching the Trigger select used to drop both filters
        it('keeps a resource-bound activity log notification bound when its trigger is re-selected', () => {
            const next = setSimpleFilterValue(options, '$activity_log_entry_created', boundToFlag, 'activity-log')

            expect(next.events?.[0].properties).toEqual(boundToFlag.events?.[0].properties)
            expect(next.properties).toEqual(boundToFlag.properties)
        })

        it('drops the previous event filters when a different trigger is chosen', () => {
            const next = setSimpleFilterValue(options, '$early_access_feature_updated', boundToFlag, 'activity-log')

            expect(next.events?.[0]).toEqual({
                id: '$early_access_feature_updated',
                name: 'Early access feature updated',
                type: 'events',
            })
        })
    })
})
