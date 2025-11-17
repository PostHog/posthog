import { expectLogic, partial } from 'kea-test-utils'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { initKeaTests } from '~/test/init'
import { PropertyDefinition, PropertyDefinitionState, PropertyDefinitionType, PropertyType } from '~/types'

const propertyDefinitions: PropertyDefinition[] = [
    {
        id: 'an id',
        name: 'no property type',
        description: 'a description',
        type: PropertyDefinitionType.Event,
    },
    {
        id: 'an id',
        name: 'a string',
        description: 'a description',
        property_type: PropertyType.String,
        type: PropertyDefinitionType.Event,
    },
    {
        id: 'an id',
        name: '$time',
        description: 'a description',
        property_type: PropertyType.DateTime,
        type: PropertyDefinitionType.Event,
    },
    {
        id: 'an id',
        name: '$timestamp',
        description: 'a description',
        property_type: PropertyType.DateTime,
        type: PropertyDefinitionType.Event,
    },
]

const groupPropertyDefinitions: PropertyDefinition[] = [
    {
        id: 'an id',
        name: 'no property type',
        description: 'a description',
        type: PropertyDefinitionType.Group,
    },
    {
        id: 'an id',
        name: 'a string',
        description: 'a description',
        property_type: PropertyType.String,
        type: PropertyDefinitionType.Group,
    },
    {
        id: 'an id',
        name: '$time',
        description: 'a description',
        property_type: PropertyType.DateTime,
        type: PropertyDefinitionType.Group,
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
                    const filteredPropertyDefinitions =
                        req.url.searchParams.get('type') === 'group' &&
                        req.url.searchParams.get('group_type_index') !== null
                            ? groupPropertyDefinitions
                            : propertyDefinitions
                    const foundProperties = filteredPropertyDefinitions.filter(
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
                logic.actions.loadPropertyDefinitions(['a string'], PropertyDefinitionType.Event)
            })
                .toDispatchActions([
                    logic.actionCreators.updatePropertyDefinitions({
                        'event/a string': PropertyDefinitionState.Pending,
                    }),
                    logic.actionCreators.fetchAllPendingDefinitions(),
                    logic.actionCreators.updatePropertyDefinitions({
                        'event/a string': PropertyDefinitionState.Loading,
                    }),
                    logic.actionCreators.updatePropertyDefinitions({
                        'event/a string': propertyDefinitions.find(
                            ({ name }) => name === 'a string'
                        ) as PropertyDefinition,
                    }),
                ])
                .toMatchValues({
                    propertyDefinitionStorage: partial({
                        'event/a string': propertyDefinitions.find(({ name }) => name === 'a string'),
                    }),
                })
            expect(logic.values.propertyDefinitionsByType('event')).toEqual([
                {
                    description: 'Duration of the session',
                    id: '$session_duration',
                    is_seen_on_filtered_events: false,
                    is_numerical: true,
                    name: '$session_duration',
                    property_type: 'Duration',
                },
                propertyDefinitions.find(({ name }) => name === 'a string'),
            ])
        })

        it('can load group property definitions when correct group type index is provided', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadPropertyDefinitions(['a string'], PropertyDefinitionType.Group, 1)
            })
                .toDispatchActions([
                    logic.actionCreators.updatePropertyDefinitions({
                        'group/1/a string': PropertyDefinitionState.Pending,
                    }),
                    logic.actionCreators.fetchAllPendingDefinitions(),
                    logic.actionCreators.updatePropertyDefinitions({
                        'group/1/a string': PropertyDefinitionState.Loading,
                    }),
                    logic.actionCreators.updatePropertyDefinitions({
                        'group/1/a string': groupPropertyDefinitions.find(
                            ({ name }) => name === 'a string'
                        ) as PropertyDefinition,
                    }),
                ])
                .toMatchValues({
                    propertyDefinitionStorage: partial({
                        'group/1/a string': groupPropertyDefinitions.find(({ name }) => name === 'a string'),
                    }),
                })

            // invalid or wrong group type, should not return any properties
            expect(logic.values.propertyDefinitionsByType('group')).toEqual([])
            expect(logic.values.propertyDefinitionsByType('group', 0)).toEqual([])
            expect(logic.values.propertyDefinitionsByType('group', 1)).toEqual([
                groupPropertyDefinitions.find(({ name }) => name === 'a string'),
            ])
        })

        it('handles network errors', async () => {
            // run twice to assure errors get retried
            for (let i = 0; i < 2; i++) {
                await expectLogic(logic, () => {
                    logic.actions.loadPropertyDefinitions(['network error'], PropertyDefinitionType.Event)
                })
                    .toDispatchActions([
                        logic.actionCreators.updatePropertyDefinitions({
                            'event/network error': PropertyDefinitionState.Pending,
                        }),
                        logic.actionCreators.fetchAllPendingDefinitions(),
                        logic.actionCreators.updatePropertyDefinitions({
                            'event/network error': PropertyDefinitionState.Error,
                        }),
                    ])
                    .toMatchValues({
                        propertyDefinitionStorage: partial({ 'event/network error': PropertyDefinitionState.Error }),
                    })
            }
        })

        it('handles missing definitions', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadPropertyDefinitions(['this is not there'], PropertyDefinitionType.Event)
            })
                .toDispatchActions([
                    logic.actionCreators.updatePropertyDefinitions({
                        'event/this is not there': PropertyDefinitionState.Pending,
                    }),
                    logic.actionCreators.fetchAllPendingDefinitions(),
                    logic.actionCreators.updatePropertyDefinitions({
                        'event/this is not there': PropertyDefinitionState.Missing,
                    }),
                ])
                .toMatchValues({
                    propertyDefinitionStorage: partial({ 'event/this is not there': PropertyDefinitionState.Missing }),
                })
        })

        it('handles local definitions', async () => {
            await expectLogic(logic, () => {
                logic.actions.loadPropertyDefinitions(['$session_duration'], PropertyDefinitionType.Event)
            })
                .toFinishAllListeners()
                .toNotHaveDispatchedActions(['updatePropertyDefinitions'])
                .toMatchValues({
                    propertyDefinitionStorage: {
                        'event/$session_duration': partial({ name: '$session_duration' }),
                        'session/snapshot_source': partial({ name: 'snapshot_source' }),
                        'event_metadata/$group_0': {
                            id: '$group_0',
                            name: 'organization',
                            property_type: 'String',
                            type: 'event_metadata',
                        },
                        'event_metadata/$group_1': {
                            id: '$group_1',
                            name: 'instance',
                            property_type: 'String',
                            type: 'event_metadata',
                        },
                        'event_metadata/$group_2': {
                            id: '$group_2',
                            name: 'project',
                            property_type: 'String',
                            type: 'event_metadata',
                        },
                        'event_metadata/distinct_id': partial({ name: 'distinct_id' }),
                        'event_metadata/event': partial({ name: 'event' }),
                        'event_metadata/person_id': partial({ name: 'person_id' }),
                        'event_metadata/person_mode': partial({ name: 'person_mode' }),
                        'event_metadata/timestamp': partial({
                            name: 'timestamp',
                        }),
                        'resource/assignee': partial({ name: 'assignee' }),
                        'resource/first_seen': partial({ name: 'first_seen' }),
                    },
                })
        })
    })

    describe('lazy loading', () => {
        it('lazy loads a property with getPropertyDefinition()', async () => {
            expect(logic.values.getPropertyDefinition('$time', PropertyDefinitionType.Event)).toEqual(null)
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.getPropertyDefinition('$time', PropertyDefinitionType.Event)).toEqual(
                partial({ name: '$time', property_type: 'DateTime' })
            )
        })

        it('lazy loads a property with describeProperty()', async () => {
            expect(logic.values.describeProperty('$time', PropertyDefinitionType.Event)).toEqual(null)
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.describeProperty('$time', PropertyDefinitionType.Event)).toEqual('DateTime')
        })

        it('lazy loads a property with formatPropertyValueForDisplay()', async () => {
            expect(logic.values.formatPropertyValueForDisplay('$time', 1661332948)).toEqual('1661332948')
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.formatPropertyValueForDisplay('$time', 1661332948)).toEqual('2022-08-24 09:22:28')
        })

        it('does not refetch missing properties', async () => {
            expect(logic.values.describeProperty('not a prop', PropertyDefinitionType.Event)).toEqual(null)
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
                    propertyDefinitionStorage: partial({ 'event/not a prop': PropertyDefinitionState.Missing }),
                })
            expect(logic.values.describeProperty('not a prop', PropertyDefinitionType.Event)).toEqual(null)
            await expectLogic(logic)
                .delay(15)
                .toFinishAllListeners()
                .toNotHaveDispatchedActions(['loadPropertyDefinitions'])
                .toMatchValues({
                    propertyDefinitionStorage: partial({ 'event/not a prop': PropertyDefinitionState.Missing }),
                })
        })

        it('works with different types', async () => {
            expect(logic.values.describeProperty('not a prop', PropertyDefinitionType.Event)).toEqual(null)
            await expectLogic(logic)
                .delay(15)
                .toFinishAllListeners()
                .toMatchValues({
                    propertyDefinitionStorage: partial({ 'event/not a prop': PropertyDefinitionState.Missing }),
                })
            expect(logic.values.describeProperty('$time', PropertyDefinitionType.Person)).toEqual(null)
            await expectLogic(logic)
                .delay(15)
                .toFinishAllListeners()
                .toMatchValues({
                    propertyDefinitionStorage: partial({
                        'event/not a prop': PropertyDefinitionState.Missing,
                        'person/$time': partial({ name: '$time', property_type: 'DateTime' }),
                    }),
                })
        })
    })

    describe('formatting properties', () => {
        beforeEach(async () => {
            await expectLogic(() => {
                logic.actions.loadPropertyDefinitions(
                    ['a string', '$timestamp', 'no property type'],
                    PropertyDefinitionType.Event
                )
            }).toFinishAllListeners()
        })

        describe('formatting simple properties', () => {
            it('does not describe a property that has no server provided type', () => {
                expect(logic.values.describeProperty('no property type', PropertyDefinitionType.Event)).toBeNull()
            })

            it('does not describe a property that has not yet been cached', () => {
                expect(logic.values.describeProperty('not yet cached', PropertyDefinitionType.Event)).toBeNull()
            })

            it('does describe a property that has a server provided type', () => {
                expect(logic.values.describeProperty('a string', PropertyDefinitionType.Event)).toEqual('String')
                expect(logic.values.describeProperty('$timestamp', PropertyDefinitionType.Event)).toEqual('DateTime')
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
