import { PropertyType } from '~/src/types'

import { getPropertyType } from './property-defs-utils'

describe('PropertyDefsUtils', () => {
    describe('getPropertyType', () => {
        const testCases: [string, any, PropertyType | null][] = [
            // Special key prefixes
            ['utm_source', 'google', PropertyType.String],
            ['utm_medium', 123, PropertyType.String],
            ['$feature/my_flag', true, PropertyType.String],
            ['$feature_flag_response', false, PropertyType.String],
            ['$survey_response', 'yes', PropertyType.String],
            ['$survey_response_2', 123, PropertyType.String],

            // String values
            ['key', 'hello', PropertyType.String],
            ['key', 'true', PropertyType.Boolean],
            ['key', 'false', PropertyType.Boolean],
            ['key', 'TRUE', PropertyType.Boolean],
            ['key', 'FALSE', PropertyType.Boolean],
            ['key', '2024-01-01T00:00:00Z', PropertyType.DateTime],
            ['key', '2024-01-01T00:00:00+00:00', PropertyType.DateTime],
            ['key', 'invalid-date', PropertyType.String],

            // Number values
            ['key', 123, PropertyType.Numeric],
            ['timestamp', 1234567890, PropertyType.Numeric],
            ['TIME', 1234567890, PropertyType.Numeric],
            ['key', 123.45, PropertyType.Numeric],
            ['key', -123, PropertyType.Numeric],
            ['key', 0, PropertyType.Numeric],

            // Boolean values
            ['key', true, PropertyType.Boolean],
            ['key', false, PropertyType.Boolean],

            // Edge cases
            ['key', null, null],
            ['key', undefined, null],
        ]
        it.each(testCases)('should derive the correct property type for %s: %s', (key, value, expected) => {
            const result = getPropertyType(key, value)

            expect(result).toEqual(expected)
        })
    })
})
