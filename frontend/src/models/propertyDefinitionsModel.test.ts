import { initKeaTests } from '~/test/init'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { expectLogic, partial } from 'kea-test-utils'
import { PropertyDefinition, PropertyDefinitionState, PropertyType } from '~/types'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useMocks } from '~/mocks/jest'

const propertyDefinitions: PropertyDefinition[] = [
    {
        id: 'an id',
        name: 'no property type',
        description: 'a description',
        volume_30_day: null,
        query_usage_30_day: null,
    },
    {
        id: 'an id',
        name: 'a string',
        description: 'a description',
        volume_30_day: null,
        query_usage_30_day: null,
        property_type: PropertyType.String,
    },
    {
        id: 'an id',
        name: '$time',
        description: 'a description',
        volume_30_day: null,
        query_usage_30_day: null,
        property_type: PropertyType.DateTime,
    },
    {
        id: 'an id',
        name: '$timestamp',
        description: 'a description',
        volume_30_day: null,
        query_usage_30_day: null,
        property_type: PropertyType.DateTime,
    },
]

describe('the property definitions model', () => {
    let logic: ReturnType<typeof propertyDefinitionsModel.build>
    let featureFlagsLogic: ReturnType<typeof featureFlagLogic.build>

    beforeEach(async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/property_definitions/': (req) => {
                    const propertiesToFind = (req.url.searchParams.get('properties') || '').split(',')
                    if (propertiesToFind[0] === 'network error') {
                        return
                    }
                    const foundProperties = propertyDefinitions.filter(
                        (p) => propertiesToFind.length === 0 || propertiesToFind.includes(p.name)
                    )
                    return [
                        200,
                        {
                            count: foundProperties.length,
                            results: foundProperties,
                            next: undefined,
                        },
                    ]
                },
            },
        })

        initKeaTests()
        featureFlagsLogic = featureFlagLogic()
        featureFlagsLogic.mount()
        logic = propertyDefinitionsModel()
        logic.mount()
    })

    describe('loading properties', () => {
        it('can load property definitions', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadPropertyDefinitions(['a string'])
            })
                .toDispatchActions([
                    logic.actionCreators.updatePropertyDefinitions({ 'a string': PropertyDefinitionState.Pending }),
                    logic.actionCreators.fetchAllPendingDefinitions(),
                    logic.actionCreators.updatePropertyDefinitions({ 'a string': PropertyDefinitionState.Loading }),
                    logic.actionCreators.updatePropertyDefinitions({
                        'a string': propertyDefinitions.find(({ name }) => name === 'a string') as PropertyDefinition,
                    }),
                ])
                .toMatchValues({
                    propertyDefinitionStorage: partial({
                        'a string': propertyDefinitions.find(({ name }) => name === 'a string'),
                    }),
                    propertyDefinitions: [
                        {
                            description: 'Duration of the session',
                            id: '$session_duration',
                            is_seen_on_filtered_events: false,
                            is_numerical: true,
                            name: '$session_duration',
                            property_type: 'Duration',
                        },
                        propertyDefinitions.find(({ name }) => name === 'a string'),
                    ],
                })
        })

        it('handles network errors', async () => {
            // run twice to assure errors get retried
            for (let i = 0; i < 2; i++) {
                await expectLogic(logic, () => {
                    logic.actions.loadPropertyDefinitions(['network error'])
                })
                    .toDispatchActions([
                        logic.actionCreators.updatePropertyDefinitions({
                            'network error': PropertyDefinitionState.Pending,
                        }),
                        logic.actionCreators.fetchAllPendingDefinitions(),
                        logic.actionCreators.updatePropertyDefinitions({
                            'network error': PropertyDefinitionState.Error,
                        }),
                    ])
                    .toMatchValues({
                        propertyDefinitionStorage: partial({ 'network error': PropertyDefinitionState.Error }),
                    })
            }
        })

        it('handles missing definitions', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadPropertyDefinitions(['this is not there'])
            })
                .toDispatchActions([
                    logic.actionCreators.updatePropertyDefinitions({
                        'this is not there': PropertyDefinitionState.Pending,
                    }),
                    logic.actionCreators.fetchAllPendingDefinitions(),
                    logic.actionCreators.updatePropertyDefinitions({
                        'this is not there': PropertyDefinitionState.Missing,
                    }),
                ])
                .toMatchValues({
                    propertyDefinitionStorage: partial({ 'this is not there': PropertyDefinitionState.Missing }),
                })
        })

        it('handles local definitions', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadPropertyDefinitions(['$session_duration'])
            })
                .toFinishAllListeners()
                .toNotHaveDispatchedActions(['updatePropertyDefinitions'])
                .toMatchValues({
                    propertyDefinitionStorage: { $session_duration: partial({ name: '$session_duration' }) },
                })
        })
    })

    describe('lazy loading', () => {
        it('lazy loads a property with getPropertyDefinition()', async () => {
            expect(logic.values.getPropertyDefinition('$time')).toEqual(null)
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.getPropertyDefinition('$time')).toEqual(
                partial({ name: '$time', property_type: 'DateTime' })
            )
        })

        it('lazy loads a property with describeProperty()', async () => {
            expect(logic.values.describeProperty('$time')).toEqual(null)
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.describeProperty('$time')).toEqual('DateTime')
        })

        it('lazy loads a property with formatPropertyValueForDisplay()', async () => {
            expect(logic.values.formatPropertyValueForDisplay('$time', 1661332948)).toEqual('1661332948')
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.formatPropertyValueForDisplay('$time', 1661332948)).toEqual('2022-08-24 09:22:28')
        })

        it('does not refetch missing properties', async () => {
            expect(logic.values.describeProperty('not a prop')).toEqual(null)
            await expectLogic(logic)
                .delay(15)
                .toFinishAllListeners()
                .toDispatchActions([
                    'loadPropertyDefinitions',
                    'fetchAllPendingDefinitions',
                    'updatePropertyDefinitions',
                    'updatePropertyDefinitions',
                ])
                .toMatchValues({
                    propertyDefinitionStorage: partial({ 'not a prop': PropertyDefinitionState.Missing }),
                })
            expect(logic.values.describeProperty('not a prop')).toEqual(null)
            await expectLogic(logic)
                .delay(15)
                .toFinishAllListeners()
                .toNotHaveDispatchedActions(['loadPropertyDefinitions'])
                .toMatchValues({
                    propertyDefinitionStorage: partial({ 'not a prop': PropertyDefinitionState.Missing }),
                })
        })
    })

    describe('formatting properties', () => {
        beforeEach(async () => {
            await expectLogic(() => {
                logic.actions.loadPropertyDefinitions(['a string', '$timestamp', 'no property type'])
            }).toFinishAllListeners()
        })

        describe('formatting simple properties', () => {
            it('does not describe a property that has no server provided type', () => {
                expect(logic.values.describeProperty('no property type')).toBeNull()
            })

            it('does not describe a property that has not yet been cached', () => {
                expect(logic.values.describeProperty('not yet cached')).toBeNull()
            })

            it('does describe a property that has a server provided type', () => {
                expect(logic.values.describeProperty('a string')).toEqual('String')
                expect(logic.values.describeProperty('$timestamp')).toEqual('DateTime')
            })

            it('can format a property with no formatting needs for display', () => {
                expect(logic.values.formatPropertyValueForDisplay('a string', '1641368752.908')).toEqual(
                    '1641368752.908'
                )
            })

            it('can format an unknown property for display', () => {
                expect(
                    logic.values.formatPropertyValueForDisplay('not a known property type', '1641368752.908')
                ).toEqual('1641368752.908')
            })

            it('can format an null property key for display', () => {
                expect(logic.values.formatPropertyValueForDisplay(null, '1641368752.908')).toEqual('1641368752.908')
            })
        })

        describe('formatting datetime properties', () => {
            it('can format a unix timestamp as seconds with fractional part for display', () => {
                expect(logic.values.formatPropertyValueForDisplay('$timestamp', '1641368752.908')).toEqual(
                    '2022-01-05 07:45:52'
                )
            })

            it('can format a unix timestamp as milliseconds for display', () => {
                expect(logic.values.formatPropertyValueForDisplay('$timestamp', '1641368752908')).toEqual(
                    '2022-01-05 07:45:52'
                )
            })

            it('can format a unix timestamp as seconds for display', () => {
                expect(logic.values.formatPropertyValueForDisplay('$timestamp', '1641368752')).toEqual(
                    '2022-01-05 07:45:52'
                )
            })

            it('can format a date string for display', () => {
                expect(logic.values.formatPropertyValueForDisplay('$timestamp', '2022-01-05')).toEqual('2022-01-05')
            })

            it('can format a datetime string for display', () => {
                expect(logic.values.formatPropertyValueForDisplay('$timestamp', '2022-01-05 07:45:52')).toEqual(
                    '2022-01-05 07:45:52'
                )
            })

            it('can format an array of datetime string for display', () => {
                expect(
                    logic.values.formatPropertyValueForDisplay('$timestamp', ['1641368752.908', 1641368752.908])
                ).toEqual(['2022-01-05 07:45:52', '2022-01-05 07:45:52'])
            })
        })

        describe('formatting duration properties', () => {
            it('can format a number to duration', () => {
                expect(logic.values.formatPropertyValueForDisplay('$session_duration', 60)).toEqual('00:01:00')
            })

            it('can format a string to duration', () => {
                expect(logic.values.formatPropertyValueForDisplay('$session_duration', '60')).toEqual('00:01:00')
            })

            it('handles non numbers', () => {
                expect(logic.values.formatPropertyValueForDisplay('$session_duration', 'blah')).toEqual('blah')
            })
        })

        it('can format a null value for display', () => {
            expect(logic.values.formatPropertyValueForDisplay('$timestamp', null)).toEqual(null)
            expect(logic.values.formatPropertyValueForDisplay('$timestamp', undefined)).toEqual(null)
        })
    })
})
