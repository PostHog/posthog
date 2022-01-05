import { initKeaTestLogic } from '~/test/init'
import { propertyDefinitionsModel } from '~/models/propertyDefinitionsModel'
import { expectLogic } from 'kea-test-utils'
import { defaultAPIMocks, mockAPI } from 'lib/api.mock'
import { PropertyDefinition } from '~/types'

jest.mock('lib/api')

describe('the property definitions model', () => {
    let logic: ReturnType<typeof propertyDefinitionsModel.build>

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
            property_type: 'String',
            property_type_format: undefined,
        },
        {
            id: 'an id',
            name: '$time',
            description: 'a description',
            volume_30_day: null,
            query_usage_30_day: null,
            property_type: 'DateTime',
            property_type_format: 'unix_timestamp',
        },
        {
            id: 'an id',
            name: '$timestamp',
            description: 'a description',
            volume_30_day: null,
            query_usage_30_day: null,
            property_type: 'DateTime',
            property_type_format: 'YYYY-MM-DD hh:mm:ss',
        },
    ]

    mockAPI(async (url) => {
        if (url.pathname === 'api/projects/@current/property_definitions/') {
            return {
                count: 3,
                results: propertyDefinitions,
                next: undefined,
            }
        }
        return defaultAPIMocks(url)
    })

    initKeaTestLogic({
        logic: propertyDefinitionsModel,
        props: {},
        onLogic: (l) => (logic = l),
    })

    it('can load property definitions', () => {
        expectLogic(logic).toMatchValues({
            propertyDefinitions,
        })
    })

    it('does not describe a property that has no server provided type', () => {
        expect(logic.values.describeProperty('no property type')).toBeNull()
    })

    it('does describe a property that has a server provided type but no format', () => {
        expect(logic.values.describeProperty('a string')).toEqual('String')
    })

    it('does describe a property that has a server provided type and format', () => {
        expect(logic.values.describeProperty('$timestamp')).toEqual('DateTime (YYYY-MM-DD hh:mm:ss)')
        expect(logic.values.describeProperty('$time')).toEqual('DateTime (unix_timestamp)')
    })

    it('can format a property with no formatting needs for display', () => {
        expect(logic.values.formatForDisplay('a string', '1641368752.908')).toEqual('1641368752.908')
    })

    it('can format an unknown property for display', () => {
        expect(logic.values.formatForDisplay('not a known property type', '1641368752.908')).toEqual('1641368752.908')
    })

    it('can format a timestamp for display', () => {
        expect(logic.values.formatForDisplay('$time', '1641368752.908')).toEqual('2022-01-05 07:45:52')
    })
})
