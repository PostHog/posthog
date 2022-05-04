import { initKeaTests } from '~/test/init'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { expectLogic } from 'kea-test-utils'
import { PropertyDefinition, PropertyType } from '~/types'
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
                '/api/projects/@current/property_definitions/': {
                    count: 3,
                    results: propertyDefinitions,
                    next: undefined,
                },
            },
        })

        initKeaTests()
        featureFlagsLogic = featureFlagLogic()
        featureFlagsLogic.mount()
        logic = propertyDefinitionsModel()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadPropertyDefinitionsSuccess'])
    })

    it('can load property definitions', () => {
        expectLogic(logic).toMatchValues({ propertyDefinitions })
    })

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
        expect(logic.values.formatForDisplay('a string', '1641368752.908')).toEqual('1641368752.908')
    })

    it('can format an unknown property for display', () => {
        expect(logic.values.formatForDisplay('not a known property type', '1641368752.908')).toEqual('1641368752.908')
    })

    it('can format an undefined property key for display', () => {
        expect(logic.values.formatForDisplay(undefined, '1641368752.908')).toEqual('1641368752.908')
    })

    describe('formatting datetime properties', () => {
        it('can format a unix timestamp as seconds with fractional part for display', () => {
            expect(logic.values.formatForDisplay('$timestamp', '1641368752.908')).toEqual('2022-01-05 07:45:52')
        })

        it('can format a unix timestamp as milliseconds for display', () => {
            expect(logic.values.formatForDisplay('$timestamp', '1641368752908')).toEqual('2022-01-05 07:45:52')
        })

        it('can format a unix timestamp as seconds for display', () => {
            expect(logic.values.formatForDisplay('$timestamp', '1641368752')).toEqual('2022-01-05 07:45:52')
        })

        it('can format a date string for display', () => {
            expect(logic.values.formatForDisplay('$timestamp', '2022-01-05')).toEqual('2022-01-05')
        })

        it('can format a datetime string for display', () => {
            expect(logic.values.formatForDisplay('$timestamp', '2022-01-05 07:45:52')).toEqual('2022-01-05 07:45:52')
        })

        it('can format an array of datetime string for display', () => {
            expect(logic.values.formatForDisplay('$timestamp', ['1641368752.908', 1641368752.908])).toEqual([
                '2022-01-05 07:45:52',
                '2022-01-05 07:45:52',
            ])
        })
    })

    it('can format a null value for display', () => {
        expect(logic.values.formatForDisplay('$timestamp', null)).toEqual(null)
        expect(logic.values.formatForDisplay('$timestamp', undefined)).toEqual(null)
    })
})
